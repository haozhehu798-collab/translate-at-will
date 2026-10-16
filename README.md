# 快捷翻译 · Windows 全局划词翻译 / 截图 OCR / AI 助手

**简体中文** | [English](README.en.md)

一个常驻系统托盘的 Windows 小工具：在**任意软件、任意界面**里，选中英文（或框选屏幕）按一个快捷键，就能查词、翻译、问 AI。**单 exe、绿色免安装、不依赖运行环境**，可拷贝到任意 Win10/11 电脑直接使用。

## 功能特性

- **全局划词翻译**：鼠标选中单词、短语、整句、整段，按快捷键即在鼠标旁弹出结果。
- **框选截图 OCR**：选不中的文字（扫描版 PDF、图片、视频、禁用复制的软件）框选即译；按键瞬间冻结屏幕快照，连右键菜单、下拉菜单等“一碰就消失”的界面也能完整截下。OCR 由 Windows 本地引擎完成，**不联网、不上传图片**。
- **多行逐行对照**：多行/整段内容按“原文行 → 译文行”逐句对照，空行保留段落，译文复制保留换行。
- **单词多来源聚合**：缩写（如 TEC）会列全论文库专业释义、词典全称、网络释义等，不遗漏专业含义。
- **AI 助手**：对话窗自由提问（回车发送、Shift+回车换行）；结果窗可一键 **AI 精译**（长句/段落更通顺、术语更准）和 **AI 详解**（单词/缩写）。
- 支持译文自动复制、开机自启、查词历史、英美音发音、图形化设置。

## 快速开始（普通用户）

1. 到本仓库的 **Releases** 下载最新版 `快捷翻译.exe`。
2. 双击运行，程序在右下角托盘待命（无需安装 Python 或任何运行库）。
3. 选中英文按快捷键即可；首次运行会在 exe 同目录自动生成空白 `config.ini`。

| 功能 | 出厂快捷键（可在设置中改为任意键，如 F1/F2/F3） |
| --- | --- |
| 划词翻译 | `Ctrl + Alt + E` |
| 截图 OCR 翻译 | `Ctrl + Alt + S` |
| AI 提问 | `Ctrl + Alt + A` |

详细图文说明见 [`docs/使用说明.md`](docs/使用说明.md)。

## 可选配置（在托盘右键“设置”里填写）

- **AI 助手**：OpenAI 兼容接口，支持 DeepSeek、豆包(火山方舟)、OpenAI、自定义；填 API Key 与模型即可启用 AI 精译/详解/对话。
- **百度翻译官方 API**：标准版免费，填写后长句翻译质量更好；留空则使用内置免费通道。

## 从源码运行

需要 Windows 10/11、Python 3.11+：

```powershell
pip install -r requirements.txt
python src/fanyi.py
```

> 从源码运行时，`config.ini`、`history.csv`、`cache/` 统一生成在项目根目录。

## 打包成单文件 exe

先安装依赖与 PyInstaller（也可使用项目内的 `.build_env` 虚拟环境，脚本会自动识别）：

```powershell
pip install -r requirements.txt pyinstaller
# Windows PowerShell：
& scripts/build_exe.ps1
```

打包脚本会按自身位置自动定位项目根，拷到任意目录/电脑都能直接打包；产物 `快捷翻译.exe` 生成在 `build_pkg/dist/` 并自动复制到项目根目录。

## 目录结构

```
.
├─ src/
│  ├─ fanyi.py            # 主程序源码
│  └─ app.ico             # 程序图标
├─ scripts/
│  ├─ build_exe.ps1       # PyInstaller 打包脚本（自动定位路径）
│  └─ make_icon.py        # 图标生成脚本
├─ docs/
│  └─ 使用说明.md          # 详细图文使用说明
├─ README.md              # 中文说明（本文件）
├─ README.en.md           # English README
├─ LICENSE                # MIT 许可证
├─ requirements.txt       # 源码运行依赖
├─ config.example.ini     # 配置模板（密钥留空）
├─ .gitignore
├─ 快捷翻译.exe            # 打包成品（建议放 GitHub Releases，不入仓库）
├─ config.ini             # 你的真实配置（含密钥，已被忽略）
└─ history.csv            # 个人查词历史（已被忽略）
```

## 安全与隐私（重要）

- **`config.ini` 含明文 API Key，绝不要上传到 GitHub 或直接发给他人**；它已写入 `.gitignore`。
- 分享给别人使用时：**只发 `快捷翻译.exe`（可附 `docs/使用说明.md`）即可**，对方首次运行会自动生成空白配置；不要把自己的 `config.ini`、`history.csv` 一起发出。
- `.build_env/`（虚拟环境）、`build_pkg/`（打包中间产物）、`cache/`（运行缓存）均与具体机器相关，不应提交。
- 若不慎把 API Key 提交或外发，请立即到对应服务商后台**吊销并重置 Key**。

## 许可证

[MIT](LICENSE)

## 免责声明

本工具为个人学习用途，免费翻译依赖公共接口，使用时请遵守相应服务的条款。
