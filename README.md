# Pawly

`Pawly` 是一个运行在 Windows 桌面的像素猫桌宠，能够接入 OpenClaw，会根据连接状态、最近会话和任务状态切换动作、表情与掉落金币效果。

## 目录

- [功能概览](#功能概览)
- [项目结构](#项目结构)
- [环境要求](#环境要求)
- [新手推荐用法](#新手推荐用法)
- [快速开始](#快速开始)
  - [1. 安装依赖](#1-安装依赖)
  - [2. 配置 OpenClaw](#2-配置-openclaw)
  - [3. 直接运行](#3-直接运行)
- [打包 EXE](#打包-exe)
- [部署说明](#部署说明)
- [OpenClaw 接入说明](#openclaw-接入说明)
  - [设备 ID 配对流程](#设备-id-配对流程)

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

## 新手推荐用法

如果你只是想先把桌宠跑起来，不打算改代码，推荐按下面这条路径走。

### 最优启动路径

1. 安装 Python 3.11 或 3.12
2. 执行依赖安装：`python -m pip install -r requirements.txt`
3. 执行一次打包：`powershell -ExecutionPolicy Bypass -File .\build_windows_exes.ps1`
4. 日常使用时，直接双击 `PawlyPanel.exe`
5. 在面板里填 OpenClaw 地址，点击“启动小猫”

### 为什么推荐这样用

- `PawlyPanel.exe` 更适合新手，不需要先开 CMD
- 面板会保存你的 OpenClaw 地址和 Token 配置
- 面板可以直接启动和关闭小猫
- 如果你只是使用，不建议平时直接运行 `desktop_cat.py`

### 最省事的日常使用

首次打包完成后，后面通常只需要：

1. 双击 `PawlyPanel.exe`
2. 点击“启动小猫”

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

推荐优先运行控制面板：

```powershell
python .\desktop_cat_panel.pyw
```

或者直接运行打包后的面板：

```powershell
.\PawlyPanel.exe
```

如果你是在调试源码，也可以直接运行桌宠：

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

### 设备 ID 配对流程

如果 OpenClaw 提示 `pairing-required` 或 `not-paired`，按下面做：

1. 先打开 `PawlyPanel.exe`
2. 填好 OpenClaw 地址，然后点一次“启动小猫”
3. 回到面板，查看“设备 ID（OpenClaw 配对用）”
4. 点击“复制 ID”
5. 到 OpenClaw 服务端批准这个 Device ID
6. 再次启动或等待小猫重连

说明：

- 不需要去翻日志找设备 ID
- 面板里显示的就是当前小猫使用的 Device ID
- 如果设备 ID 还没生成，面板会提示你先启动一次小猫
- `openclaw_device_identity.json` 里也能看到同一个 `deviceId`，但不要公开整个文件，因为里面还包含私钥
