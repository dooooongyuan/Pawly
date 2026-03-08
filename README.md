# Pawly

`Pawly` 是一个运行在 Windows 桌面的像素猫桌宠，能够接入 OpenClaw，会根据连接状态、最近会话和任务状态切换动作、表情与掉落金币效果。

## 功能概览

- 右下角桌宠悬浮，支持拖拽并记住位置
- 基于横向动作表播放多组待机、走动、奔跑、睡觉、扑倒、伸懒腰动作
- 接入 OpenClaw 后自动检测最近会话，不再依赖手工绑定固定会话
- 任务触发时生成金币、银币、红币，小猫会主动移动并执行扑币动作
- 连接成功、失败、任务完成时显示不同头顶表情
- 提供独立控制面板 `PawlyPanel.exe`，不需要先手动开 CMD

## 项目结构

- `desktop_cat.py`：桌宠主程序
- `desktop_cat_panel.pyw`：控制面板
- `build_windows_exes.ps1`：Windows 一键打包脚本
- `Cat Sprite Sheet.png`：猫动作表
- `Coin_Gems/`：金币动画资源
- `pipo-popupemotes Split images/`：表情资源
- `desktop_cat_panel_config.example.json`：OpenClaw 配置示例

## 环境要求

- Windows 10/11
- Python 3.11 或 3.12
- 可访问的 OpenClaw 服务，建议使用 HTTPS
- 如果需要打包 EXE，需要安装 `PyInstaller`

## 快速开始

### 1. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 2. 配置 OpenClaw

复制示例配置：

```powershell
Copy-Item .\desktop_cat_panel_config.example.json .\desktop_cat_panel_config.json
```

编辑 `desktop_cat_panel_config.json`：

```json
{
  "openclaw_url": "127.0.0.1:18789",
  "openclaw_token": ""
}
```

说明：

- `openclaw_url` 不是固定写法，下面几种都支持：
  - `127.0.0.1:18789`
  - `192.168.1.20:18789`
  - `your-server-ip:18789`
  - `http://127.0.0.1:18789`
  - `https://your-openclaw.example.com`
  - `https://your-openclaw.example.com/overview`
- 如果没写协议，程序会自动补成 `http://`
- 如果是 `https://`，程序会自动走 `wss://`
- 如果地址里带了 `/overview`、`/chat` 这类控制台路径，程序会自动去掉末尾页面后缀
- `openclaw_token` 可以先留空，首次配对成功后本地会生成认证文件
- 如果你的 OpenClaw 需要先配对，先在 OpenClaw 网页端完成设备配对

### 3. 直接运行

运行控制面板：

```powershell
python .\desktop_cat_panel.pyw
```

或者直接运行桌宠：

```powershell
python .\desktop_cat.py
```

## 打包 EXE

执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows_exes.ps1
```

打包完成后会生成：

- `Pawly.exe`
- `PawlyPanel.exe`

建议日常使用直接启动 `PawlyPanel.exe`。

## 部署说明

如果你要部署到另一台 Windows 机器，至少带上这些文件：

- `Pawly.exe`
- `PawlyPanel.exe`
- `Cat Sprite Sheet.png`
- `Coin_Gems/`
- `pipo-popupemotes Split images/`

首次部署流程：

1. 启动 `PawlyPanel.exe`
2. 填写 OpenClaw 地址和 Token
3. 如果 OpenClaw 提示需要配对，先在服务端确认设备配对
4. 点击启动桌宠
5. 桌宠会在右下角出现，并自动保存拖拽后的位置

## OpenClaw 接入说明

当前逻辑：

- 未连接时：显示断连表情，猫保持睡觉
- 刚连接成功时：显示连接成功表情约 3 秒，然后隐藏
- 自动模式下：监听最近会话，收到用户新消息后判定为“开始干活”
- 干活期间：掉落金币，小猫会移动到金币附近并执行扑币动作
- 任务完成后：金币清空，显示完成表情约 3 秒，然后恢复普通行为

本地运行时会自动生成这些状态文件：

- `desktop_cat_runtime.json`
- `desktop_cat_state.json`
- `desktop_cat_session_state.json`
- `openclaw_device_identity.json`
- `openclaw_device_auth.json`

这些文件包含运行状态、设备身份或认证信息，不应提交到公共仓库。
