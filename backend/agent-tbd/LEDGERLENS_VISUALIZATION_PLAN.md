# LedgerLens — Spending Analysis Visualization Development Plan

## Context

LedgerLens is a receipt-tracking app. The spending analysis page currently displays raw data tables (by store, by payment type, by system category, by sub-category). We need to add rich visualizations so users can intuitively understand their spending breakdown at a glance.

The data model already supports:
- Receipts with date, store, payment type, total amount
- Items on each receipt with amount
- Hierarchical categories: Level I (e.g. "Grocery") → Level II (e.g. "Dairy", "Frozen", "Snacks") → Level III
- Existing summary stats: total receipts count, total amount
- Existing filters: time frame ("All time" dropdown)

We are adding **3 new visualization components** to the analysis page. All 3 sit above the existing tables. The existing tables remain unchanged for now.

---

## Feature 1: Stacked Horizontal Progress Bar (Category Overview)

### What it is
A single full-width horizontal bar (100% width), divided into colored segments. Each segment represents a Level I category, sized proportionally by spending amount. This replaces the current "Top 3 Spending" text-only display in the summary card.

### Placement
Inside the top summary card, below "Total Receipts" and "Total Amount", spanning the full width of the card.

### Requirements
- Each segment's width = (category amount / total amount) × 100%
- Each segment has a distinct color. Use a consistent color palette that maps to categories throughout the whole page (same colors reused in Feature 3 donut chart).
- On hover over a segment: show a tooltip with category name, amount, and percentage.
- Segments should have a small 1-2px gap or border between them for visual separation.
- Categories sorted by amount descending (largest segment on the left).
- If a category is < 2% of total, collapse it into an "Other" segment at the far right.
- Below the bar, show a legend row: colored dot + category name + amount + percentage for each visible segment. Use a horizontal flex layout that wraps if needed.

### Data needed
```
Array<{ categoryName: string; amount: number; color: string; percentage: number }>
```
Derived from the existing "by system category" data.

### Interaction
- Clicking a segment in the progress bar scrolls to / highlights that category in the donut chart (Feature 3) and drills into it.

---

## Feature 2: Summary Stat Cards Row

### What it is
A horizontal row of 4-5 stat cards, each showing one key metric as a large number with a small label underneath. Similar to a KPI dashboard row.

### Placement
Directly below the top summary card (which has the progress bar), above the tables.

### Cards to include (in this order, left to right)

1. **Avg per Trip**
   - Value: total amount / total receipts count, formatted as currency
   - Label: "AVG PER TRIP"

2. **Most Expensive Trip**
   - Value: the highest single receipt total, formatted as currency
   - Sub-label: store name + date of that receipt (smaller text below the label)
   - Label: "BIGGEST TRIP"

3. **Most Visited Store**
   - Value: store name
   - Sub-label: visit count + total amount at that store
   - Label: "MOST VISITED"

4. **Top Category at Top Store**
   - Value: category name (e.g. "Dairy")
   - Sub-label: amount spent on that category at the most visited store
   - Label: "TOP BUY AT [STORE NAME]"
   - This tells the user "you go to T&T the most, and when you're there, you mostly buy Dairy"

5. **Month-over-Month Change** (only show if there's data for at least 2 months)
   - Value: percentage change (e.g. "+12.3%" or "-5.1%")
   - Color: green if spending went down, red if spending went up (from a budgeting perspective, spending less = good)
   - Sub-label: "vs last month"
   - Label: "MONTHLY CHANGE"

### Design
- Each card: white background, subtle border or shadow, rounded corners
- Large number/value: bold, ~24-28px
- Label: uppercase, muted gray, ~11-12px, letter-spacing
- Sub-label: regular weight, muted, ~13px
- Cards are equal width, evenly distributed in a responsive flex/grid row
- On mobile: 2 columns, cards wrap

---

## Feature 3: Interactive Drillable Donut Chart

### What it is
A donut chart that starts showing Level I category breakdown, and when the user clicks a segment, it drills into that category to show its Level II sub-categories as a new donut. Clicking again on a Level II segment drills into Level III if available.

### Placement
A new card/section below the stat cards row, above the existing tables. The card has:
- Title: "Spending Breakdown"
- Time frame selector (dropdown or tabs): "All Time", "This Month", "Last 30 Days", "Last 3 Months", "Last 6 Months", "This Year". Default matches the page-level filter.
- The donut chart itself
- A breadcrumb trail for drill navigation (e.g. "All Categories > Grocery > Dairy")

### Layout inside the card
- Left side (60%): the donut chart
- Right side (40%): a legend/list showing each segment with color dot, name, amount, percentage — sorted by amount descending

### Donut chart requirements
- Center of the donut shows: the total amount for the current view level, and a label (e.g. "Total" or the parent category name if drilled in)
- Use the same color palette as Feature 1's progress bar for Level I categories. When drilling into a Level II, use lighter/darker shades of the parent color.
- Smooth animation when transitioning between drill levels (segments animate out, new segments animate in)
- On hover over a segment: slight pull-out effect (segment moves outward ~5px) + tooltip with name, amount, percentage

### Drill interaction
- **Click a donut segment** → drill into that category. The donut re-renders showing sub-categories of the clicked category. The center label updates to the drilled category name + its total. Breadcrumb updates.
- **Click breadcrumb item** → navigate back to that level
- **Back button or "All Categories" breadcrumb** → return to Level I view

### Breadcrumb
- Format: `All Categories > Grocery > Dairy`
- Each breadcrumb item is clickable to navigate to that level
- Show below the title, above the chart

### Time frame selector
- Changing the time frame re-queries/filters the data and updates both the donut and the legend
- The time frame selector is local to this card (does not affect the rest of the page)

### Edge cases
- If a level has only 1 sub-category, still show the donut (it'll be a full ring) but note this in the legend
- If a level has no sub-categories (leaf node), don't allow further drilling — show a tooltip or visual indicator that this is the deepest level
- Categories with 0 amount in the selected time frame should be hidden

### Data needed
The existing hierarchical category data: Level I → Level II → Level III, each with an amount. Filtering by time frame means re-aggregating receipt item amounts within the date range.

---

## General Guidelines

### Color Palette
Define a single categorical color palette (8-10 colors) used consistently across all 3 features. Map each Level I category to a fixed color. Suggested approach:
- Grocery → green (#4CAF50 or similar)
- Household → blue-gray (#78909C)
- Health → orange (#FF9800)
- Tax & Fees → neutral gray (#BDBDBD)
- Extend with more colors as categories grow

### Responsiveness
- All components must work on mobile (min-width 320px)
- Progress bar: stays full width, legend wraps
- Stat cards: 2-column grid on mobile
- Donut chart: stack legend below the chart on mobile instead of side-by-side

### Animation
- Use CSS transitions or a charting library's built-in animation (whatever the current tech stack supports)
- Keep animations under 300ms, ease-out timing
- No animation on initial page load — only on interaction (drill, hover, filter change)

### Accessibility
- All chart segments must have aria-labels with category name, amount, percentage
- Color is not the only differentiator — the legend always accompanies the chart
- Tooltips are keyboard-accessible (focusable segments)

### Implementation order
1. Feature 1 (Stacked Progress Bar) — simplest, immediate visual impact
2. Feature 2 (Stat Cards) — straightforward data aggregation + layout
3. Feature 3 (Donut Chart) — most complex due to drill interaction + time frame filtering

### Tech notes
- Use whatever charting library is already in the project. If none exists, use `recharts` for React projects or `Chart.js` for vanilla JS.
- If using recharts: PieChart for the donut (set `innerRadius`), custom active shape for hover effect
- If using Chart.js: Doughnut chart type, register click handler for drill
- The progress bar (Feature 1) does NOT need a charting library — it's a simple flex row of colored divs with percentage widths
