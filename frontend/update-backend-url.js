#!/usr/bin/env node
/**
 * 自动从后端端口配置文件读取并更新 .env.local
 */
const fs = require('fs');
const path = require('path');

const CONFIG_FILE = path.join(__dirname, '..', 'backend-port.json');
const ENV_FILE = path.join(__dirname, '.env.local');

function updateBackendUrl() {
  try {
    // Read backend port config
    if (!fs.existsSync(CONFIG_FILE)) {
      console.log('⚠️  Backend port config file not found, using default port 8000');
      console.log('   Tip: Start the backend server first');
      return;
    }

    const config = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
    const backendUrl = config.url;

    console.log(`📡 Backend detected at: ${backendUrl}`);

    // Read .env.local
    if (!fs.existsSync(ENV_FILE)) {
      console.log('❌ .env.local file not found');
      return;
    }

    let envContent = fs.readFileSync(ENV_FILE, 'utf-8');

    // Update NEXT_PUBLIC_API_URL
    const urlRegex = /^NEXT_PUBLIC_API_URL=.+$/m;
    const newLine = `NEXT_PUBLIC_API_URL=${backendUrl}`;

    if (urlRegex.test(envContent)) {
      envContent = envContent.replace(urlRegex, newLine);
      console.log(`✅ Updated NEXT_PUBLIC_API_URL -> ${backendUrl}`);
    } else {
      envContent += `\n${newLine}\n`;
      console.log(`✅ Added NEXT_PUBLIC_API_URL -> ${backendUrl}`);
    }

    // Write back
    fs.writeFileSync(ENV_FILE, envContent, 'utf-8');
    console.log('✓ .env.local updated');

  } catch (error) {
    console.error('❌ Update failed:', error.message);
  }
}

updateBackendUrl();
