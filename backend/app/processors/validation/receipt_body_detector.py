"""
Receipt body detector / receipt body estimation 小票主体检测与区域估计

================================================================================
模块说明 (Module overview)
================================================================================

本模块负责：根据 OCR 文本块（带归一化坐标）估计「小票主体区域」，并过滤掉落在主体外的块
（例如背景上的竖排字、桌子上的其他文字）。所有位置相关逻辑均采用「相对（内容/宽度）」，
不依赖整张图片的绝对归一化坐标，从而适应不同拍摄方式（整图、裁切、倾斜等）。

This module: Given OCR text blocks with normalized coordinates, estimates the
"receipt body" region and filters out blocks outside it (e.g. vertical text on
background, text on table). All position logic is content-relative or
width-relative, so it does not rely on fixed image-normalized thresholds and
works across different framing (full scene, tight crop, etc.).

================================================================================
子模块 / 功能说明 (What each part does)
================================================================================

1) filter_blocks_by_receipt_body(blocks)
   - 输入：已按 (y, x) 排序的 block 列表，每个 block 含 center_x, center_y, is_amount 等。
   - 输出：仅保留落在「小票主体」内的 block。
   - 用途：在 coordinate_extractor 提取 blocks 后调用，避免右侧/背景竖排字被当成商品名等。

   Input: List of blocks (with center_x, center_y, is_amount, etc.), already sorted by (y, x).
   Output: Only blocks inside the estimated receipt body.
   Use: Called after coordinate_extractor produces blocks; avoids treating background/vertical text as items.

2) get_receipt_body_bounds(blocks)
   - 输入：同上 block 列表。
   - 输出：估计的主体区域边界字典（left_bound, right_bound, y_keep_min, header_y_cutoff, y_min, y_max, center_x），
     用于调试或 API 返回，便于前端/测试验证「有效信息是否都被框进新方块」。

   Input: Same block list as above.
   Output: Dict of estimated bounds (left_bound, right_bound, header_y_cutoff, y_min, y_max, center_x)
   for debugging or API response so you can verify all valid info is inside the box.

3) 相对位置逻辑 (Relative-position logic)

   a) Header（小票顶部 = 店名/地址/电话/时间）
      - 不再使用固定 center_y < 0.25（那是整图归一化，随拍摄变化无效）。
      - 做法：先算所有 block 的垂直范围 y_min, y_max；取「内容顶部比例」HEADER_FRACTION
        （例如 0.25），即 header_y_cutoff = y_min + HEADER_FRACTION * (y_max - y_min)。
      - center_y < header_y_cutoff 的 block 视为 header，用它们的 center_x 取平均得到
        小票中心线，用于后续左右边界对称估计。

   b) 左右边界 (Left/right bounds) — 相对位置，不以绝对 0-1 定死
      - 商店名区域（header）的 center_x 取平均作为「小票中心」store_center_x。
      - 仅用「商店名下方」的 body 部分：body = center_y > header_y_cutoff 的 blocks；在 body 上取
        body_left = min(center_x), body_right = max(center_x)。
      - 以 store_center_x 为对称中心，取 half_span = max(store_center_x - body_left, body_right - store_center_x)
        + BODY_X_PADDING，得到 left_bound = store_center_x - half_span，right_bound = store_center_x + half_span。
      - 夹到 [MIN_LEFT_BOUND, MAX_RIGHT_BOUND]，避免越界。

   c) Y 方向 (Vertical) — 目标：找到店名行 y，new_y = y*0.8，y < new_y 的都不要
      - Step 1: 从上往下扫，第一次与 GROCERY_STORE_NAMES 模糊匹配（约 1 字母 off）的 block 视为店名行，取其 center_y。
      - Step 2: new_y = store_name_y_top * ABOVE_STORE_DROP_FRACTION（0.8）。所有 center_y < new_y 的 block 丢弃。
      - 找不到时退回：用「内容高度」相对 25%（y_min + 0.25*(y_max-y_min)）作为 store_name_y_top，不做绝对分位。

   d) 过滤 (Filtering)
      - 仅保留 center_y >= y_keep_min 且 left_bound <= center_x <= right_bound 的 block。

4) 预留扩展 (Future extensions)
   - 本模块可扩展：判断「是否为小票」、拒绝非小票上传、小票类型/版式分类等；
     与「坐标提取」解耦，便于单独测试与迭代。
================================================================================
"""

from typing import Dict, Any, List, Tuple, Optional
import re
import logging

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Header 的定义 (Definition of "header")
# -----------------------------------------------------------------------------
# Header = 内容垂直范围内「靠上的那一截」的 blocks，不是单指商店名往上的部分。
# 具体：内容总高度 (y_min ~ y_max)，取前 HEADER_FRACTION（如 25%）为一条线 header_y_cutoff；
#       center_y < header_y_cutoff 的 block 都算 header。所以 header 里既有「屏幕顶到店名之间」
#       的杂项（促销、草稿纸等），也有店名、地址、时间等。用 header 是为了估计店名中心 X 和店名起始 Y。
#
# Header = the set of blocks in the top HEADER_FRACTION of content height (y_min to y_max).
# So header = "top 25% of content by height" — includes garbage above receipt + store name/address.
HEADER_FRACTION = 0.25

# -----------------------------------------------------------------------------
# 店名行 Y 与「店名以上」丢弃 (Store name row Y & drop above)
# -----------------------------------------------------------------------------
# 目标逻辑：1) 找到店名行（如 T&T Supermarket），取其 y；2) new_y = y * 0.8；3) y < new_y 的全部 drop。
# 实现：先按文本匹配「店名」行（见 _find_store_name_y），找不到再退回 header 分位数估计。
ABOVE_STORE_DROP_FRACTION = 0.8
# 退回方案：若未匹配到店名行，用「内容高度」的相对 25% 作为店名区起始 y（y_min + 0.25*(y_max-y_min)），不做绝对分位
STORE_NAME_Y_DEFAULT_FRACTION = 0.25
# Body 左右：在 body 的 min/max(center_x) 基础上向两侧各加 BODY_X_PADDING（相对冗余）
# Add this padding each side of body X span
BODY_X_PADDING = 0.02
# 左右边界夹到 [MIN_LEFT_BOUND, MAX_RIGHT_BOUND]
MIN_LEFT_BOUND = 0.01
MAX_RIGHT_BOUND = 0.99

# 美加常见超市/杂货店名（小写，用于从上往下扫、首次模糊匹配即视为店名行）。可后续接 DB 或缓存。
GROCERY_STORE_NAMES: frozenset[str] = frozenset({
    "walmart", "costco", "target", "kroger", "safeway", "trader joe's", "trader joes", "whole foods",
    "publix", "albertsons", "heb", "meijer", "sams club", "sam's club", "cvs", "walgreens",
    "food lion", "hannaford", "giant", "stop & shop", "stop and shop", "ralphs", "fred meyer",
    "king soopers", "smith's", "frys", "fry's", "vons", "pavilions", "acme", "jewel", "jewel-osco",
    "loblaws", "loblaw", "sobeys", "metro", "iga", "t&t", "tnt", "t and t", "99 ranch", "99 ranch market",
    "h mart", "hmart", "mitsuwa", "wegmans", "aldi", "lidl", "save mart", "food 4 less", "food maxx",
    "winco", "sprouts", "aldi", "aldi usa", "pick n save", "mariano's", "roundy's", "harris teeter",
    "piggly wiggly", "hy-vee", "wegmans", "market basket", "shoprite", "wegmans", "price chopper",
    "tops", "giant eagle", "weis", "brookshire", "united", "super one", "cub foods", "cub",
    "food city", "inglis", "basha's", "bashas", "stater bros", "gelson's", "gelsons",
    "bristol farms", "grocery outlet", "grocery outlet bargain market", "smart & final",
    "northgate market", "vallarta", "super king", "zion market", "h mart", "99 ranch",
    "great wall", "ranch 99", "island gourmet", "longo's", "longos", "freshco", "no frills",
    "real canadian superstore", "superstore", "zehrs", "fortinos", "provigo", "maxi",
    "save-on-foods", "save on foods", "thrifty foods", "overwaited", "city market",
    "amazon fresh", "whole foods market", "fresh thyme", "earth fare", "natural grocers",
})

# 促销/非店名：含这些的不参与店名匹配
PROMO_OR_NON_STORE_KEYWORDS = (
    "download", "join now", "offer", "earn", "rewards", "reawards", "enjoy ", "grocery delivery",
    "下載", "加入", "積分", "立即", "app", "online", " R&", "生鮮", "送到家"
)


def _normalize_for_store_match(text: str) -> str:
    """Lowercase, replace & with ' and ', collapse non-alphanumeric to space, collapse spaces."""
    if not text:
        return ""
    t = text.lower().strip()
    t = re.sub(r"\s*&\s*", " and ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _edit_distance_one(a: str, b: str) -> bool:
    """True if a and b are equal or differ by at most one character (insert/delete/substitute)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    # len(a) <= len(b)
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    if i == len(a):
        return len(b) == len(a) + 1
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:]
    return a[i:] == b[i + 1:]


def _block_matches_store_name(text: str) -> bool:
    """True if normalized text matches any GROCERY_STORE_NAMES (substring or ~1 letter off)."""
    if not text or len(text.strip()) < 3:
        return False
    t = _normalize_for_store_match(text)
    if not t:
        return False
    if any(k in (text or "").lower() for k in PROMO_OR_NON_STORE_KEYWORDS):
        return False
    for name in GROCERY_STORE_NAMES:
        n = _normalize_for_store_match(name)
        if not n or len(n) < 3:
            continue
        if n in t or t in n:
            return True
        if abs(len(t) - len(n)) <= 1 and _edit_distance_one(t, n):
            return True
    return False


def _find_store_name_y(blocks: List[Dict[str, Any]], header_blocks: List[Dict[str, Any]]) -> Optional[float]:
    """
    从上往下扫：第一条与 GROCERY_STORE_NAMES 做约 1 字母 off 模糊匹配的 block 视为店名行，返回其 center_y。
    找不到则返回 None，由调用方用「内容高度 25%」作为 default。
    """
    sorted_by_y = sorted(blocks, key=lambda b: b.get("center_y", 0))
    for b in sorted_by_y:
        text = (b.get("text") or "").strip()
        if _block_matches_store_name(text):
            y = b.get("center_y")
            if y is not None:
                logger.info("Receipt body: store name row y=%.4f text=%r", y, text[:60])
                return float(y)
    return None


def _compute_receipt_body_bounds(blocks: List[Dict[str, Any]]) -> Tuple[float, float, float, float, float, float, float]:
    """
    Compute bounds using generalized rule:
    1. Find store name (center + y position)
    2. Left bound = min(non-amount blocks center_x in body)
    3. Right bound = max(amount blocks center_x)
    4. Padding = 0.2 * (right - left) on each side
    5. Y cutoff: drop blocks with y < store_name_y * 0.8
    
    Returns (left_bound, right_bound, y_keep_min, header_y_cutoff, y_min, y_max, store_center_x).
    """
    ys = [b.get("center_y", 0) for b in blocks]
    y_min, y_max = min(ys), max(ys)
    if y_max <= y_min:
        header_y_cutoff = y_min
        header_blocks = blocks[: max(1, len(blocks) // 5)]
    else:
        header_y_cutoff = y_min + HEADER_FRACTION * (y_max - y_min)
        header_blocks = [b for b in blocks if b.get("center_y", 0) < header_y_cutoff]
        if not header_blocks:
            header_blocks = blocks[: max(1, len(blocks) // 5)]

    store_center_x = sum(b["center_x"] for b in header_blocks) / len(header_blocks)
    
    # Step 1: Find store name row Y
    store_name_y_top = _find_store_name_y(blocks, header_blocks)
    if store_name_y_top is None:
        store_name_y_top = y_min + STORE_NAME_Y_DEFAULT_FRACTION * (y_max - y_min)
        logger.debug("Receipt body: no store name match, fallback store_name_y_top=%.4f (y_min + %.0f%% of height)", store_name_y_top, STORE_NAME_Y_DEFAULT_FRACTION * 100)
    
    # Step 2: Y cutoff = store_name_y * 0.8 (drop blocks above this)
    y_keep_min = store_name_y_top * ABOVE_STORE_DROP_FRACTION

    # Step 3: Body blocks (below store name cutoff)
    body_blocks = [b for b in blocks if b.get("center_y", 0) >= y_keep_min]
    if not body_blocks:
        body_blocks = blocks
    
    # Step 4: Find left and right boundaries
    # Right bound = max X of amount blocks (receipt's amount column)
    amount_blocks_body = [b for b in body_blocks if b.get("is_amount")]
    if amount_blocks_body:
        body_right = max(b.get("center_x", 0) for b in amount_blocks_body)
    else:
        # Fallback: use all body blocks
        body_right = max(b.get("center_x", 0) for b in body_blocks)
    
    # Left bound = min X of non-amount blocks in body (item names column)
    non_amount_blocks_body = [b for b in body_blocks if not b.get("is_amount")]
    if non_amount_blocks_body:
        body_left = min(b.get("center_x", 0) for b in non_amount_blocks_body)
    else:
        # Fallback: use all body blocks
        body_left = min(b.get("center_x", 0) for b in body_blocks)
    
    # Step 5: Padding = 0.2 * (right - left)
    span = body_right - body_left
    padding = 0.2 * span if span > 0 else 0.02
    left_bound = max(MIN_LEFT_BOUND, body_left - padding)
    right_bound = min(MAX_RIGHT_BOUND, body_right + padding)
    
    logger.info(
        f"Receipt body bounds: store_name_y={store_name_y_top:.4f} y_keep_min={y_keep_min:.4f} "
        f"body_left={body_left:.4f} body_right={body_right:.4f} padding={padding:.4f} "
        f"final_bounds=[{left_bound:.4f}, {right_bound:.4f}]"
    )

    return left_bound, right_bound, y_keep_min, header_y_cutoff, y_min, y_max, store_center_x


def get_receipt_body_bounds(blocks: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    返回估计的小票主体边界（归一化 0-1），供调试或 API 使用。
    Returns estimated receipt body bounds (normalized 0-1) for debugging or API.
    """
    if not blocks:
        return {}
    left_bound, right_bound, y_keep_min, header_y_cutoff, y_min, y_max, store_center_x = _compute_receipt_body_bounds(blocks)
    return {
        "left_bound": round(left_bound, 4),
        "right_bound": round(right_bound, 4),
        "y_keep_min": round(y_keep_min, 4),
        "header_y_cutoff": round(header_y_cutoff, 4),
        "y_min": round(y_min, 4),
        "y_max": round(y_max, 4),
        "center_x": round(store_center_x, 4),
    }


def filter_blocks_by_receipt_body(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    只保留落在估计的「小票主体」内的 block：商店名为中心，下方 body 定左右界（相对）+ padding；
    Y 从商店名顶部往上留一点 padding，再上面的字全部 drop。
    Keep only blocks inside the estimated receipt body (store-name center, body X span + padding, Y from store top).

    Args:
        blocks: List of block dicts with center_x, center_y, is_amount, etc. (e.g. from coordinate_extractor).
                Should already be sorted by (y, x) for consistent header = top-of-content.

    Returns:
        Filtered list of blocks with center_y >= y_keep_min and left_bound <= center_x <= right_bound.
    """
    if not blocks:
        return blocks

    left_bound, right_bound, y_keep_min, header_y_cutoff, y_min, y_max, store_center_x = _compute_receipt_body_bounds(blocks)

    filtered = [
        b for b in blocks
        if b.get("center_y", 0) >= y_keep_min and left_bound <= b.get("center_x", 0) <= right_bound
    ]
    dropped = len(blocks) - len(filtered)
    if dropped > 0:
        logger.info(
            "Receipt body filter (relative): y_keep_min=%.3f store_center_x=%.3f bounds=[%.3f, %.3f] "
            "y_span=[%.3f, %.3f] kept=%d dropped=%d",
            y_keep_min, store_center_x, left_bound, right_bound, y_min, y_max, len(filtered), dropped,
        )
    return filtered
