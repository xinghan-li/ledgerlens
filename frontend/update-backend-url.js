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
    // 读取后端端口配置
    if (!fs.existsSync(CONFIG_FILE)) {
      console.log('⚠️  后端端口配置文件不存在，使用默认端口 8000');
      console.log('   提示: 请先启动后端服务器');
      return;
    }

    const config = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
    const backendUrl = config.url;

    console.log(`📡 检测到后端运行在: ${backendUrl}`);

    // 读取 .env.local
    if (!fs.existsSync(ENV_FILE)) {
      console.log('❌ .env.local 文件不存在');
      return;
    }

    let envContent = fs.readFileSync(ENV_FILE, 'utf-8');

    // 更新 NEXT_PUBLIC_API_URL
    const urlRegex = /^NEXT_PUBLIC_API_URL=.+$/m;
    const newLine = `NEXT_PUBLIC_API_URL=${backendUrl}`;

    if (urlRegex.test(envContent)) {
      envContent = envContent.replace(urlRegex, newLine);
      console.log(`✅ 已更新 NEXT_PUBLIC_API_URL -> ${backendUrl}`);
    } else {
      envContent += `\n${newLine}\n`;
      console.log(`✅ 已添加 NEXT_PUBLIC_API_URL -> ${backendUrl}`);
    }

    // 写回文件
    fs.writeFileSync(ENV_FILE, envContent, 'utf-8');
    console.log('✓ .env.local 已更新');

  } catch (error) {
    console.error('❌ 更新失败:', error.message);
  }
}

updateBackendUrl();
