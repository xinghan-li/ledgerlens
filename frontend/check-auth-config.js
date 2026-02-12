#!/usr/bin/env node
/**
 * 检查 Supabase Auth 配置是否正确
 */
const fs = require('fs');
const path = require('path');

const ENV_FILE = path.join(__dirname, '.env.local');

console.log('🔍 检查 Supabase Auth 配置...\n');

// 检查 .env.local 文件
if (!fs.existsSync(ENV_FILE)) {
  console.error('❌ .env.local 文件不存在！');
  console.log('   请复制 .env.local.example 并填写配置\n');
  process.exit(1);
}

const envContent = fs.readFileSync(ENV_FILE, 'utf-8');
const lines = envContent.split('\n');

const config = {};
lines.forEach(line => {
  const match = line.match(/^([A-Z_]+)=(.+)$/);
  if (match) {
    config[match[1]] = match[2];
  }
});

let hasError = false;

// 检查必需的配置
console.log('📋 配置检查:\n');

// Supabase URL
if (config.NEXT_PUBLIC_SUPABASE_URL) {
  if (config.NEXT_PUBLIC_SUPABASE_URL.includes('your-project')) {
    console.log('⚠️  NEXT_PUBLIC_SUPABASE_URL: 使用示例值，需要更新');
    hasError = true;
  } else {
    console.log('✅ NEXT_PUBLIC_SUPABASE_URL:', config.NEXT_PUBLIC_SUPABASE_URL);
  }
} else {
  console.log('❌ NEXT_PUBLIC_SUPABASE_URL: 未设置');
  hasError = true;
}

// Supabase Anon Key
if (config.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
  if (config.NEXT_PUBLIC_SUPABASE_ANON_KEY.includes('your-anon-key')) {
    console.log('⚠️  NEXT_PUBLIC_SUPABASE_ANON_KEY: 使用示例值，需要更新');
    hasError = true;
  } else {
    console.log('✅ NEXT_PUBLIC_SUPABASE_ANON_KEY:', config.NEXT_PUBLIC_SUPABASE_ANON_KEY.substring(0, 20) + '...');
  }
} else {
  console.log('❌ NEXT_PUBLIC_SUPABASE_ANON_KEY: 未设置');
  hasError = true;
}

// Backend URL
if (config.NEXT_PUBLIC_API_URL) {
  console.log('✅ NEXT_PUBLIC_API_URL:', config.NEXT_PUBLIC_API_URL);
} else {
  console.log('⚠️  NEXT_PUBLIC_API_URL: 未设置（将使用默认值）');
}

console.log('\n📝 下一步:\n');

if (hasError) {
  console.log('1. 打开 Supabase Dashboard: https://app.supabase.com');
  console.log('2. 选择你的项目');
  console.log('3. 进入 Settings → API');
  console.log('4. 复制以下值到 .env.local:');
  console.log('   - Project URL → NEXT_PUBLIC_SUPABASE_URL');
  console.log('   - anon/public key → NEXT_PUBLIC_SUPABASE_ANON_KEY');
  console.log('\n5. 配置 Redirect URLs:');
  console.log('   - 进入 Authentication → URL Configuration');
  console.log('   - 在 Redirect URLs 添加:');
  console.log('     http://localhost:3000/auth/callback');
  console.log('     http://localhost:3001/auth/callback');
  console.log('\n6. 重启前端服务: npm run dev\n');
} else {
  console.log('✅ 配置看起来正确！\n');
  console.log('如果登录仍有问题，请检查:');
  console.log('1. Supabase Dashboard → Authentication → URL Configuration');
  console.log('   确认 Redirect URLs 包含: http://localhost:3000/auth/callback');
  console.log('\n2. 访问诊断页面: http://localhost:3000/auth-debug');
  console.log('   查看详细的配置和状态信息');
  console.log('\n3. 查看调试文档: frontend/MAGIC_LINK_DEBUG.md\n');
}
