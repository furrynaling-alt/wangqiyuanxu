# -*- mode: python ; coding: utf-8 -*-
# 往栖缘叙 PyInstaller 打包配置
# 用法: pyinstaller 往栖缘叙.spec
import os

py_dir = os.path.dirname(os.path.abspath('I:/往栖缘叙/py/app.py'))
app_root = os.path.dirname(py_dir)
public_dir = os.path.join(app_root, 'public')
vendor_dir = os.path.join(py_dir, 'vendor')

a = Analysis(
    [os.path.join(py_dir, 'app.py')],
    pathex=[py_dir, vendor_dir, app_root],
    binaries=[],
    datas=[
        (public_dir, 'public'),
        (vendor_dir, 'vendor'),
    ],
    hiddenimports=['webview', 'webview.platforms.edgechromium', 'webview.platforms.winforms',
                   'clr', 'cffi', 'bottle', 'proxy_tools'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='往栖缘叙',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=os.path.join(public_dir, 'assets', 'icon.ico'),
)
