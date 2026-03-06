#!/usr/bin/env node
/**
 * 检查 Supabase Auth 配置是否正确
 */
const fs = require('fs');
const path = require('path');

const ENV_FILE = path.join(__dirname, '.env.local');

console.log('🔍 Checking Supabase Auth config...\n');

// Check .env.local
if (!fs.existsSync(ENV_FILE)) {
  console.error('❌ .env.local file not found!');
  console.log('   Copy .env.local.example and fill in the config\n');
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

// Check required config
console.log('📋 Config check:\n');

// Supabase URL
if (config.NEXT_PUBLIC_SUPABASE_URL) {
  if (config.NEXT_PUBLIC_SUPABASE_URL.includes('your-project')) {
    console.log('⚠️  NEXT_PUBLIC_SUPABASE_URL: using example value, needs update');
    hasError = true;
  } else {
    console.log('✅ NEXT_PUBLIC_SUPABASE_URL:', config.NEXT_PUBLIC_SUPABASE_URL);
  }
} else {
  console.log('❌ NEXT_PUBLIC_SUPABASE_URL: not set');
  hasError = true;
}

// Supabase Anon Key
if (config.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
  if (config.NEXT_PUBLIC_SUPABASE_ANON_KEY.includes('your-anon-key')) {
    console.log('⚠️  NEXT_PUBLIC_SUPABASE_ANON_KEY: using example value, needs update');
    hasError = true;
  } else {
    console.log('✅ NEXT_PUBLIC_SUPABASE_ANON_KEY:', config.NEXT_PUBLIC_SUPABASE_ANON_KEY.substring(0, 20) + '...');
  }
} else {
  console.log('❌ NEXT_PUBLIC_SUPABASE_ANON_KEY: not set');
  hasError = true;
}

// Backend URL
if (config.NEXT_PUBLIC_API_URL) {
  console.log('✅ NEXT_PUBLIC_API_URL:', config.NEXT_PUBLIC_API_URL);
} else {
  console.log('⚠️  NEXT_PUBLIC_API_URL: not set (default will be used)');
}

console.log('\n📝 Next steps:\n');

if (hasError) {
  console.log('1. Open Supabase Dashboard: https://app.supabase.com');
  console.log('2. Select your project');
  console.log('3. Go to Settings → API');
  console.log('4. Copy these to .env.local:');
  console.log('   - Project URL → NEXT_PUBLIC_SUPABASE_URL');
  console.log('   - anon/public key → NEXT_PUBLIC_SUPABASE_ANON_KEY');
  console.log('\n5. Configure Redirect URLs:');
  console.log('   - Go to Authentication → URL Configuration');
  console.log('   - Add to Redirect URLs:');
  console.log('     http://localhost:3000/auth/callback');
  console.log('     http://localhost:3001/auth/callback');
  console.log('\n6. Restart frontend: npm run dev\n');
} else {
  console.log('✅ Config looks good!\n');
  console.log('If login still fails, check:');
  console.log('1. Supabase Dashboard → Authentication → URL Configuration');
  console.log('   Ensure Redirect URLs includes: http://localhost:3000/auth/callback');
  console.log('\n2. Visit debug page: http://localhost:3000/auth-debug');
  console.log('   For detailed config and status');
  console.log('\n3. See frontend/MAGIC_LINK_DEBUG.md\n');
}
