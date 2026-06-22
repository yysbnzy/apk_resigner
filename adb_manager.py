#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ADBManager — ADB 设备管理器

职责：
- 设备发现、连接、授权管理
- 车机 APK 扫描（区分系统预装/第三方应用）
- APK 导出（含 Split APK 支持）
- 所有 ADB 命令的封装，自动处理多设备选择

设计约束：
- 不依赖 GUI，可被独立测试
- 复用现有 ToolManager 的 ADB 路径查找
- 所有方法返回结构化数据，不弹窗
"""

import os
import re
import json
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Union
from datetime import datetime


@dataclass
class DeviceInfo:
    """ADB 设备信息"""
    serial: str
    state: str  # 'device', 'unauthorized', 'offline', 'no_permissions'
    model: str = ""
    transport_id: str = ""
    product: str = ""
    
    @property
    def is_ready(self) -> bool:
        return self.state == 'device'
    
    @property
    def display_name(self) -> str:
        if self.model:
            return f"{self.model} ({self.serial})"
        return self.serial


@dataclass
class PackageInfo:
    """应用包信息"""
    name: str
    apk_path: str
    app_type: str  # 'SYSTEM' or 'THIRD_PARTY'
    version: str = ""
    version_code: str = ""
    is_split: bool = False
    size: int = 0
    
    @property
    def display_name(self) -> str:
        """返回包名最后一段作为显示名"""
        return self.name.split('.')[-1] if self.name else ""


@dataclass
class ExportResult:
    """APK 导出结果"""
    package: str
    base_apk: str
    splits: List[str] = field(default_factory=list)
    output_dir: str = ""
    success: bool = True
    error: str = ""


class ADBError(Exception):
    """ADB 操作错误"""
    pass


class ADBManager:
    """
    ADB 设备管理器
    
    使用示例:
        tools = ToolManager()  # 现有工具管理器
        adb = ADBManager(tools)
        
        # 列出设备
        devices = adb.list_devices()
        
        # 选择设备
        adb.select_device('abc123')
        
        # 扫描应用
        apps = adb.scan_packages()
        
        # 导出 APK
        result = adb.export_apk('com.example.app', './work')
    """
    
    # 系统应用路径前缀
    SYSTEM_PREFIXES = [
        '/system/', '/vendor/', '/product/', '/system_ext/', '/oem/'
    ]
    
    # 第三方应用路径前缀
    THIRD_PARTY_PREFIXES = [
        '/data/app/', '/data/user/'
    ]
    
    def __init__(self, tool_manager=None):
        """
        初始化 ADB 管理器
        
        Args:
            tool_manager: 现有 ToolManager 实例，用于查找 ADB 路径
        """
        self.tools = tool_manager
        self.adb_cmd: List[str] = []
        self.selected_device: Optional[str] = None
        self._adb_available: Optional[bool] = None
        
        self._init_adb()
    
    def _init_adb(self):
        """初始化 ADB 命令路径"""
        # 1. 优先从 ToolManager 获取内置 ADB
        if self.tools and hasattr(self.tools, 'get_cmd'):
            cmd = self.tools.get_cmd('adb')
            if cmd:
                self.adb_cmd = cmd
                return
        
        # 2. 检查系统 PATH
        adb_path = shutil.which('adb')
        if adb_path:
            self.adb_cmd = [adb_path]
            return
        
        # 3. 检查常见安装路径
        common_paths = [
            Path(os.environ.get('ANDROID_HOME', '')) / 'platform-tools' / 'adb',
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Android' / 'Sdk' / 'platform-tools' / 'adb',
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Android' / 'platform-tools' / 'adb',
        ]
        for path in common_paths:
            if path.exists():
                self.adb_cmd = [str(path)]
                return
        
        # 4. 回退到 'adb'，希望它在 PATH 中
        self.adb_cmd = ['adb']
    
    def is_available(self) -> bool:
        """检查 ADB 是否可用（含缓存）"""
        if self._adb_available is None:
            self._adb_available = self._test_adb()
        return self._adb_available
    
    def _test_adb(self) -> bool:
        """测试 ADB 是否可以执行"""
        try:
            result = subprocess.run(
                self.adb_cmd + ['version'],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0 and 'Android Debug Bridge' in result.stdout
        except Exception:
            return False
    
    def get_adb_version(self) -> str:
        """获取 ADB 版本号"""
        try:
            result = subprocess.run(
                self.adb_cmd + ['version'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                # 输出: Android Debug Bridge version 1.0.41
                match = re.search(r'version\s+([\d.]+)', result.stdout)
                if match:
                    return match.group(1)
            return "unknown"
        except Exception as e:
            return f"error: {e}"
    
    # ═══════════════════════════════════════════════════
    # 设备管理
    # ═══════════════════════════════════════════════════
    
    def list_devices(self) -> List[DeviceInfo]:
        """
        列出所有已连接的 ADB 设备
        
        命令: adb devices -l
        
        Returns:
            List[DeviceInfo] 设备列表
        
        Raises:
            ADBError: ADB 不可用
        """
        if not self.is_available():
            raise ADBError("ADB 不可用，请检查安装")
        
        result = self._run(['devices', '-l'])
        if result[0] != 0:
            raise ADBError(f"adb devices 失败: {result[2]}")
        
        devices = []
        for line in result[1].strip().split('\n')[1:]:  # 跳过 "List of devices attached"
            line = line.strip()
            if not line:
                continue
            
            # 解析: abc123def       device product:star model:MI_14 device:star transport_id:1
            parts = line.split()
            if len(parts) < 2:
                continue
            
            serial = parts[0]
            state = parts[1]
            
            # 解析额外字段
            model = ""
            transport_id = ""
            product = ""
            for part in parts[2:]:
                if ':' in part:
                    key, value = part.split(':', 1)
                    if key == 'model':
                        model = value.replace('_', ' ')
                    elif key == 'transport_id':
                        transport_id = value
                    elif key == 'product':
                        product = value
            
            devices.append(DeviceInfo(
                serial=serial,
                state=state,
                model=model,
                transport_id=transport_id,
                product=product
            ))
        
        return devices
    
    def select_device(self, serial: str) -> bool:
        """
        选择指定设备，后续所有命令自动附加 -s serial
        
        Args:
            serial: 设备序列号
        
        Returns:
            bool: 是否成功选择
        """
        # 验证设备存在
        devices = self.list_devices()
        for dev in devices:
            if dev.serial == serial:
                if not dev.is_ready:
                    raise ADBError(f"设备 {serial} 状态为 {dev.state}，不可用")
                self.selected_device = serial
                return True
        
        raise ADBError(f"设备 {serial} 未找到或未连接")
    
    def get_device_info(self) -> Dict[str, str]:
        """
        获取当前选中设备的详细信息
        
        Returns:
            Dict: {model, android_version, sdk_level, abi, is_rooted, ...}
        
        Raises:
            ADBError: 未选择设备
        """
        self._ensure_device_selected()
        
        props = {
            'model': self._get_prop('ro.product.model'),
            'brand': self._get_prop('ro.product.brand'),
            'android_version': self._get_prop('ro.build.version.release'),
            'sdk_level': self._get_prop('ro.build.version.sdk'),
            'abi': self._get_prop('ro.product.cpu.abi'),
            'device': self._get_prop('ro.product.device'),
            'build_id': self._get_prop('ro.build.id'),
            'security_patch': self._get_prop('ro.build.version.security_patch'),
        }
        
        # 检测是否 root
        props['is_rooted'] = str(self._is_rooted())
        
        return props
    
    def _get_prop(self, prop_name: str) -> str:
        """获取单个属性值"""
        result = self._run(['shell', 'getprop', prop_name])
        if result[0] == 0:
            return result[1].strip()
        return ""
    
    def _is_rooted(self) -> bool:
        """检测设备是否已 root"""
        try:
            result = self._run(['shell', 'su', '-c', 'id'], timeout=5)
            return result[0] == 0 and 'uid=0' in result[1]
        except Exception:
            return False
    
    def _ensure_device_selected(self):
        """确保已选择设备"""
        if not self.selected_device:
            raise ADBError("未选择设备，请先调用 select_device()")
    
    # ═══════════════════════════════════════════════════
    # 包扫描
    # ═══════════════════════════════════════════════════
    
    def scan_packages(self, flags: str = "-f") -> List[PackageInfo]:
        """
        扫描设备已安装应用
        
        命令: adb shell pm list packages -f
        
        Args:
            flags: 额外参数，如 '-f' 显示路径，'-3' 仅第三方，'-s' 仅系统
        
        Returns:
            List[PackageInfo] 应用列表
        """
        self._ensure_device_selected()
        
        result = self._run(['shell', 'pm', 'list', 'packages', '-f'])
        if result[0] != 0:
            raise ADBError(f"扫描应用失败: {result[2]}")
        
        packages = []
        for line in result[1].strip().split('\n'):
            line = line.strip()
            if not line.startswith('package:'):
                continue
            
            # 解析: package:/data/app/~~xxx==/com.example.app-xxx==/base.apk=com.example.app
            # 或: package:/system/app/Calendar/Calendar.apk=com.android.calendar
            match = re.match(r'package:(.+?)=(.+)', line)
            if not match:
                continue
            
            apk_path = match.group(1)
            package_name = match.group(2)
            
            # 判断类型
            app_type = self._classify_app_type(apk_path)
            
            packages.append(PackageInfo(
                name=package_name,
                apk_path=apk_path,
                app_type=app_type
            ))
        
        return packages
    
    def _classify_app_type(self, apk_path: str) -> str:
        """根据路径判断应用类型"""
        for prefix in self.SYSTEM_PREFIXES:
            if apk_path.startswith(prefix):
                return 'SYSTEM'
        for prefix in self.THIRD_PARTY_PREFIXES:
            if apk_path.startswith(prefix):
                return 'THIRD_PARTY'
        return 'UNKNOWN'
    
    def get_package_details(self, package_name: str) -> Dict[str, str]:
        """
        获取应用详细信息
        
        命令: adb shell dumpsys package <package>
        
        Args:
            package_name: 应用包名
        
        Returns:
            Dict: {version_name, version_code, first_install_time, signatures, ...}
        """
        self._ensure_device_selected()
        
        result = self._run(['shell', 'dumpsys', 'package', package_name])
        if result[0] != 0:
            return {}
        
        output = result[1]
        details = {}
        
        # 解析版本信息
        ver_match = re.search(r'versionName=([\S]+)', output)
        if ver_match:
            details['version_name'] = ver_match.group(1)
        
        code_match = re.search(r'versionCode=(\d+)', output)
        if code_match:
            details['version_code'] = code_match.group(1)
        
        # 解析安装时间
        time_match = re.search(r'firstInstallTime=([\S]+)', output)
        if time_match:
            details['first_install_time'] = time_match.group(1)
        
        # 解析签名
        sig_match = re.search(r'signatures:\s*\[PackageSignatures\{([\w]+)', output)
        if sig_match:
            details['signature_hash'] = sig_match.group(1)
        
        # 解析权限
        perms = re.findall(r'android\.permission\.[\w.]+', output)
        details['permissions'] = ', '.join(set(perms)[:10])  # 最多10个
        
        return details
    
    # ═══════════════════════════════════════════════════
    # APK 导出
    # ═══════════════════════════════════════════════════
    
    def get_apk_paths(self, package_name: str) -> List[str]:
        """
        获取应用的所有 APK 路径（含 Split APK）
        
        命令: adb shell pm path <package>
        
        Args:
            package_name: 应用包名
        
        Returns:
            List[str] APK 路径列表
        """
        self._ensure_device_selected()
        
        result = self._run(['shell', 'pm', 'path', package_name])
        if result[0] != 0:
            raise ADBError(f"获取 APK 路径失败: {result[2]}")
        
        paths = []
        for line in result[1].strip().split('\n'):
            line = line.strip()
            if line.startswith('package:'):
                paths.append(line.replace('package:', ''))
        
        return paths
    
    def export_apk(self, package_name: str, output_dir: Union[str, Path]) -> ExportResult:
        """
        导出 APK 到本地（含 Split APK 自动处理）
        
        步骤:
        1. pm path 获取所有 APK 路径
        2. 创建输出目录
        3. adb pull 逐个导出
        4. 返回导出结果
        
        Args:
            package_name: 应用包名
            output_dir: 输出目录
        
        Returns:
            ExportResult 导出结果
        """
        self._ensure_device_selected()
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # 1. 获取所有 APK 路径
            paths = self.get_apk_paths(package_name)
            if not paths:
                return ExportResult(
                    package=package_name,
                    base_apk="",
                    success=False,
                    error="未找到 APK 路径"
                )
            
            # 2. 创建应用专用目录
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            app_dir = output_dir / f"{package_name}_{timestamp}"
            app_dir.mkdir(parents=True, exist_ok=True)
            
            # 3. 导出 APK
            base_apk = ""
            splits = []
            
            for remote_path in paths:
                filename = Path(remote_path).name
                local_path = app_dir / filename
                
                # 执行 pull
                result = self._run(['pull', remote_path, str(local_path)], timeout=120)
                if result[0] != 0:
                    return ExportResult(
                        package=package_name,
                        base_apk="",
                        success=False,
                        error=f"导出 {filename} 失败: {result[2]}"
                    )
                
                # 判断是否为 base.apk
                if 'base.apk' in filename or filename == f"{package_name}.apk":
                    base_apk = str(local_path)
                else:
                    splits.append(str(local_path))
            
            # 如果没有找到 base.apk，默认第一个为 base
            if not base_apk and paths:
                base_apk = str(app_dir / Path(paths[0]).name)
            
            return ExportResult(
                package=package_name,
                base_apk=base_apk,
                splits=splits,
                output_dir=str(app_dir),
                success=True
            )
        
        except Exception as e:
            return ExportResult(
                package=package_name,
                base_apk="",
                success=False,
                error=str(e)
            )
    
    def export_apk_simple(self, package_name: str, output_dir: Union[str, Path]) -> str:
            return ExportResult(
                package=package_name,
                base_apk="",
                success=False,
                error=str(e)
            )
    
    def export_apk_simple(self, package_name: str, output_dir: Union[str, Path]) -> str:
        """
        简单导出：只导出 base APK，返回路径
        
        Args:
            package_name: 应用包名
            output_dir: 输出目录
        
        Returns:
            str: 导出后的 APK 路径
        """
        result = self.export_apk(package_name, output_dir)
        if not result.success:
            raise ADBError(f"导出失败: {result.error}")
        return result.base_apk
    
    # ═══════════════════════════════════════════════════
    # 安装相关
    # ═══════════════════════════════════════════════════
    
    def is_package_installed(self, package_name: str) -> bool:
        """检查应用是否已安装"""
        self._ensure_device_selected()
        
        result = self._run(['shell', 'pm', 'list', 'packages', package_name])
        return result[0] == 0 and package_name in result[1]
    
    def get_package_size(self, package_name: str) -> int:
        """获取应用大小（字节）"""
        self._ensure_device_selected()
        
        result = self._run(['shell', 'du', '-b', '-s', f'/data/app/{package_name}*'])
        if result[0] == 0:
            parts = result[1].strip().split()
            if parts:
                try:
                    return int(parts[0])
                except ValueError:
                    pass
        return 0
    
    # ═══════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════
    
    def _run(self, subcmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
        """
        执行 ADB 命令，自动附加 -s serial（如果已选择设备）
        
        Args:
            subcmd: ADB 子命令，如 ['devices', '-l']
            timeout: 超时秒数
        
        Returns:
            Tuple[int, str, str]: (returncode, stdout, stderr)
        """
        cmd = list(self.adb_cmd)  # 复制，避免修改原列表
        
        # 添加设备选择
        if self.selected_device and subcmd[0] not in ('devices', 'version', 'connect', 'disconnect'):
            cmd.extend(['-s', self.selected_device])
        
        cmd.extend(subcmd)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8',
                errors='replace'
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"命令超时 ({timeout}s): {' '.join(cmd)}"
        except Exception as e:
            return -1, "", str(e)
    
    def __repr__(self) -> str:
        return f"ADBManager(adb={' '.join(self.adb_cmd)}, device={self.selected_device})"


# ═══════════════════════════════════════════════════
# 便捷函数（无需实例化，用于简单场景）
# ═══════════════════════════════════════════════════

def quick_list_devices() -> List[DeviceInfo]:
    """快速列出设备（无需实例化 ADBManager）"""
    adb = ADBManager()
    return adb.list_devices()


def quick_export_apk(package_name: str, output_dir: str, device_serial: Optional[str] = None) -> ExportResult:
    """快速导出 APK（无需实例化）"""
    adb = ADBManager()
    if device_serial:
        adb.select_device(device_serial)
    return adb.export_apk(package_name, output_dir)


if __name__ == '__main__':
    # 简单测试
    print("ADBManager 测试")
    
    adb = ADBManager()
    
    # 检查 ADB 可用性
    print(f"ADB 可用: {adb.is_available()}")
    print(f"ADB 版本: {adb.get_adb_version()}")
    
    if adb.is_available():
        # 列出设备
        devices = adb.list_devices()
        print(f"\n已连接设备: {len(devices)}个")
        for dev in devices:
            print(f"  {dev.serial}: {dev.state} (model={dev.model})")
        
        # 如果有可用设备，尝试获取信息
        for dev in devices:
            if dev.is_ready:
                print(f"\n选择设备: {dev.display_name}")
                adb.select_device(dev.serial)
                
                info = adb.get_device_info()
                print(f"  型号: {info.get('model')}")
                print(f"  Android: {info.get('android_version')}")
                print(f"  SDK: {info.get('sdk_level')}")
                print(f"  ABI: {info.get('abi')}")
                print(f"  Root: {info.get('is_rooted')}")
                
                # 扫描第三方应用
                print(f"\n扫描第三方应用...")
                apps = adb.scan_packages()
                third_party = [a for a in apps if a.app_type == 'THIRD_PARTY']
                print(f"  第三方应用: {len(third_party)}个")
                for app in third_party[:5]:
                    print(f"    {app.name} ({app.apk_path})")
                break
