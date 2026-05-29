# Barcode_Merger

半夜闲来无事写的小工具

Barcode_Merger 是一个用于 TEMU 条码 PDF 合成的桌面工具，使用 Python 编写，界面基于 Tkinter，PDF 处理依赖 PyMuPDF。

## 下载使用

如果不需要自行运行源码或打包，可以直接从 Release 页面下载已打包好的程序：

https://github.com/Fluxtivityzz/Barcode_Merger/releases

## 功能简介

- 合成条码 PDF 文件
- 提供图形界面操作
- 支持预览与参数配置
- 可通过 PyInstaller 打包为 Windows 可执行文件

## 环境要求

- Python 3
- PyMuPDF
- PyInstaller（仅打包 exe 时需要）

推荐使用 Python 3.14.5：

https://www.python.org/downloads/release/python-3145/

## 安装依赖

进入程序目录：

```powershell
cd barcode_merger_exe
```

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

也可以单独安装 PyMuPDF：

```powershell
python -m pip install --upgrade pymupdf
```

PyMuPDF 发布页：

https://github.com/pymupdf/PyMuPDF/releases

## 运行程序

方式一：直接运行批处理文件。

```powershell
run_app.bat
```

方式二：使用 Python 启动。

```powershell
python barcode_merger_gui.py
```

方式三：从 Release 下载打包好的程序启动。

## 打包 exe

进入 `barcode_merger_exe` 目录后运行：

```powershell
build_exe.bat
```

打包完成后，可执行文件会生成在：

```text
barcode_merger_exe/dist/Barcode_Merger.exe
```

## 项目结构

```text
Barcode_Merger/
├── README.md
└── barcode_merger_exe/
    ├── barcode_merger_gui.py
    ├── worker.py
    ├── validators.py
    ├── cache.py
    ├── config.py
    ├── requirements.txt
    ├── run_app.bat
    └── build_exe.bat
```
