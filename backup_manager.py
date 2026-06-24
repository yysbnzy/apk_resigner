#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BackupManager — 备份/还原管理器

职责：
- 导出时自动备份（创建 manifest + 复制 APK）
- 备份列表管理（按包名/时间查询）
- 一键还原（从备份安装回设备）
- 备份清理（按时间/数量自动清理）

设计约束：
- 不依赖 GUI，可被独立测试
- 备份目录结构清晰，可手动管理
- 所有操作返回结构化结果
"""

import json
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Union
from datetime import datetime


@dataclass
class BackupInfo:
    """备份信息"""
    backup_dir: str
    package_name: str
    timestamp: str
    device_model: str
    device_serial: str
    android_version: str
    version_name: str
    version_code: str
    base_apk: str
    splits: List[str] = field(default_factory=list)
    size_bytes: int = 0
    
    @property
    def display_time(self) -> str:
        """返回人类可读的时间格式"""
        try:
            dt = datetime.strptime(self.timestamp, "%Y%m%d_%H%M%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return self.timestamp
    
    @property
    def display_size(self) -> str:
        """返回人类可读的文件大小"""
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        elif self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        elif self.size_bytes < 1024 * 1024 * 1024:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{self.size_bytes / (1024 * 1024 * 1024):.1f} GB"


@dataclass
class BackupResult:
    """备份操作结果"""
    success: bool
    backup_dir: str
    message: str


@dataclass
class RestoreResult:
    """还原操作结果"""
    success: bool
    message: str
    install_output: str = ""


class BackupError(Exception):
    """备份操作错误"""
    pass


class BackupManager:
    """
    备份管理器
    
    使用示例:
        backup = BackupManager()
        
        # 创建备份
        result = backup.create_backup(
            package_name='com.example.app',
            apk_paths={'base': '/path/to/base.apk', 'splits': ['/path/to/split1.apk']},
            device_info={'model': 'MI 14', 'serial': 'abc123'},
            version_info={'version_name': '1.2.3', 'version_code': '123'}
        )
        
        # 列出备份
        backups = backup.list_backups('com.example.app')
        
        # 还原备份
        result = backup.restore_backup(backup_dir, install_manager)
    """
    
    def __init__(self, backup_root: Optional[Union[str, Path]] = None):
        """
        初始化备份管理器
        
        Args:
            backup_root: 备份根目录，默认 ~/apk_resign_work/backups
        """
        if backup_root:
            self.backup_root = Path(backup_root)
        else:
            self.backup_root = Path.home() / "apk_resign_work" / "backups"
        
        self.backup_root.mkdir(parents=True, exist_ok=True)
    
    # ═══════════════════════════════════════════════════
    # 创建备份
    # ═══════════════════════════════════════════════════
    
    def create_backup(
        self,
        package_name: str,
        apk_paths: Dict[str, str],
        device_info: Dict[str, str],
        version_info: Optional[Dict[str, str]] = None
    ) -> BackupResult:
        """
        创建备份
        
        目录结构:
            backups/
            └── com.example.app_20260618_201430/
                ├── manifest.json          # 备份元信息
                ├── base.apk               # 主 APK（复制并重命名）
                └── split_config.arm64.apk # Split APK（如有）
        
        Args:
            package_name: 应用包名
            apk_paths: {'base': '/path/to/base.apk', 'splits': ['/path/to/split1.apk']}
            device_info: {'model': 'MI 14', 'serial': 'abc123', 'android_version': '14'}
            version_info: {'version_name': '1.2.3', 'version_code': '123'}
        
        Returns:
            BackupResult: 备份结果
        """
        try:
            # 1. 创建备份目录
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = self.backup_root / f"{package_name}_{timestamp}"
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            # 2. 复制 APK 文件
            base_src = Path(apk_paths.get('base', ''))
            if not base_src or not base_src.exists():
                return BackupResult(False, "", "未找到 base APK")
            
            base_dst = backup_dir / "base.apk"
            shutil.copy2(base_src, base_dst)
            total_size = base_dst.stat().st_size
            
            splits = []
            for split_src in apk_paths.get('splits', []):
                split_src = Path(split_src)
                if split_src.exists():
                    split_dst = backup_dir / split_src.name
                    shutil.copy2(split_src, split_dst)
                    splits.append(split_dst.name)
                    total_size += split_dst.stat().st_size
            
            # 3. 创建 manifest.json
            manifest = {
                "package": package_name,
                "timestamp": timestamp,
                "device_model": device_info.get('model', ''),
                "device_serial": device_info.get('serial', ''),
                "android_version": device_info.get('android_version', ''),
                "abi": device_info.get('abi', ''),
                "version_name": version_info.get('version_name', '') if version_info else '',
                "version_code": version_info.get('version_code', '') if version_info else '',
                "base_apk": "base.apk",
                "splits": splits,
                "total_size": total_size,
                "backup_tool": "apk_resigner",
                "backup_version": "2.0.2"
            }
            
            manifest_path = backup_dir / "manifest.json"
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            
            return BackupResult(
                success=True,
                backup_dir=str(backup_dir),
                message=f"备份成功: {backup_dir}"
            )
        
        except Exception as e:
            return BackupResult(
                success=False,
                backup_dir="",
                message=f"备份失败: {str(e)}"
            )
    
    def create_backup_from_export(
        self,
        export_result,
        device_info: Dict[str, str]
    ) -> BackupResult:
        """
        从 ADBManager.ExportResult 创建备份（便捷方法）
        
        Args:
            export_result: ADBManager.export_apk() 返回的结果
            device_info: 设备信息
        
        Returns:
            BackupResult
        """
        apk_paths = {
            'base': export_result.base_apk,
            'splits': export_result.splits
        }
        
        version_info = None
        # 尝试获取版本信息
        # 这里可以从 dumpsys 获取，但依赖 ADBManager
        # 简化版本：留空，由调用者填充
        
        return self.create_backup(
            package_name=export_result.package,
            apk_paths=apk_paths,
            device_info=device_info,
            version_info=version_info
        )
    
    # ═══════════════════════════════════════════════════
    # 查询备份
    # ═══════════════════════════════════════════════════
    
    def list_backups(self, package_name: Optional[str] = None) -> List[BackupInfo]:
        """
        列出备份
        
        Args:
            package_name: 指定包名则只列出该应用的备份，None 则列出所有
        
        Returns:
            List[BackupInfo] 按时间倒序排列
        """
        backups = []
        
        for item in self.backup_root.iterdir():
            if not item.is_dir():
                continue
            
            # 解析目录名: com.example.app_20260618_201430
            parts = item.name.rsplit('_', 2)
            if len(parts) < 3:
                continue
            
            pkg = '_'.join(parts[:-2])
            timestamp = '_'.join(parts[-2:])
            
            # 包名过滤
            if package_name and pkg != package_name:
                continue
            
            # 读取 manifest
            manifest_path = item / "manifest.json"
            if not manifest_path.exists():
                continue
            
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                
                backup_info = BackupInfo(
                    backup_dir=str(item),
                    package_name=manifest.get('package', pkg),
                    timestamp=manifest.get('timestamp', timestamp),
                    device_model=manifest.get('device_model', ''),
                    device_serial=manifest.get('device_serial', ''),
                    android_version=manifest.get('android_version', ''),
                    version_name=manifest.get('version_name', ''),
                    version_code=manifest.get('version_code', ''),
                    base_apk=str(item / manifest.get('base_apk', 'base.apk')),
                    splits=[str(item / s) for s in manifest.get('splits', [])],
                    size_bytes=manifest.get('total_size', 0)
                )
                backups.append(backup_info)
            
            except Exception:
                # 忽略损坏的备份
                continue
        
        # 按时间倒序
        backups.sort(key=lambda x: x.timestamp, reverse=True)
        return backups
    
    def get_backup(self, backup_dir: Union[str, Path]) -> Optional[BackupInfo]:
        """
        获取单个备份详情
        
        Args:
            backup_dir: 备份目录路径
        
        Returns:
            BackupInfo or None
        """
        backup_dir = Path(backup_dir)
        if not backup_dir.exists():
            return None
        
        manifest_path = backup_dir / "manifest.json"
        if not manifest_path.exists():
            return None
        
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            
            return BackupInfo(
                backup_dir=str(backup_dir),
                package_name=manifest.get('package', ''),
                timestamp=manifest.get('timestamp', ''),
                device_model=manifest.get('device_model', ''),
                device_serial=manifest.get('device_serial', ''),
                android_version=manifest.get('android_version', ''),
                version_name=manifest.get('version_name', ''),
                version_code=manifest.get('version_code', ''),
                base_apk=str(backup_dir / manifest.get('base_apk', 'base.apk')),
                splits=[str(backup_dir / s) for s in manifest.get('splits', [])],
                size_bytes=manifest.get('total_size', 0)
            )
        except Exception:
            return None
    
    def has_backup(self, package_name: str) -> bool:
        """检查是否有指定应用的备份"""
        backups = self.list_backups(package_name)
        return len(backups) > 0
    
    # ═══════════════════════════════════════════════════
    # 还原备份
    # ═══════════════════════════════════════════════════
    
    def restore(
        self,
        backup_dir: Union[str, Path],
        install_manager=None
    ) -> RestoreResult:
        """
        从备份还原（简化接口）
        
        直接调用 restore_backup 方法
        
        Args:
            backup_dir: 备份目录路径
            install_manager: InstallManager 实例，用于执行安装
        
        Returns:
            RestoreResult
        """
        return self.restore_backup(backup_dir, install_manager)
    
    def restore_backup(
        self,
        backup_dir: Union[str, Path],
        install_manager=None
    ) -> RestoreResult:
        """
        从备份还原
        
        Args:
            backup_dir: 备份目录路径
            install_manager: InstallManager 实例，用于执行安装
        
        Returns:
            RestoreResult
        """
        try:
            backup = self.get_backup(backup_dir)
            if not backup:
                return RestoreResult(
                    success=False,
                    message="备份不存在或已损坏"
                )
            
            # 检查文件存在
            base_apk = Path(backup.base_apk)
            if not base_apk.exists():
                return RestoreResult(
                    success=False,
                    message=f"base.apk 不存在: {base_apk}"
                )
            
            # 如果没有 install_manager，仅返回准备信息
            if not install_manager:
                splits = [s for s in backup.splits if Path(s).exists()]
                return RestoreResult(
                    success=True,
                    message=f"准备就绪: {backup.package_name} v{backup.version_name}",
                    install_output=f"base={base_apk}, splits={splits}"
                )
            
            # 使用 InstallManager 安装
            splits = [s for s in backup.splits if Path(s).exists()]
            result = install_manager.install_overwrite(
                str(base_apk),
                splits if splits else None
            )
            
            return RestoreResult(
                success=result.success,
                message=f"还原 {backup.package_name} v{backup.version_name}: {result.message}",
                install_output=result.message
            )
        
        except Exception as e:
            return RestoreResult(
                success=False,
                message=f"还原失败: {str(e)}"
            )
    
    # ═══════════════════════════════════════════════════
    # 清理备份
    # ═══════════════════════════════════════════════════
    
    def delete_backup(self, backup_dir: Union[str, Path]) -> bool:
        """
        删除备份
        
        Args:
            backup_dir: 备份目录路径
        
        Returns:
            bool: 是否成功删除
        """
        try:
            backup_dir = Path(backup_dir)
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
                return True
            return False
        except Exception:
            return False
    
    def cleanup_old_backups(
        self,
        package_name: Optional[str] = None,
        keep_count: int = 5,
        keep_days: int = 30
    ) -> Dict[str, int]:
        """
        清理旧备份
        
        Args:
            package_name: 指定包名则只清理该应用，None 则清理所有
            keep_count: 每个应用保留最近 N 个备份
            keep_days: 保留最近 N 天的备份
        
        Returns:
            Dict: {'deleted': 删除数量, 'kept': 保留数量}
        """
        deleted = 0
        kept = 0
        
        if package_name:
            backups = self.list_backups(package_name)
        else:
            # 获取所有备份
            backups = []
            for pkg_dir in self.backup_root.iterdir():
                if pkg_dir.is_dir():
                    parts = pkg_dir.name.rsplit('_', 2)
                    if len(parts) >= 3:
                        pkg = '_'.join(parts[:-2])
                        backups.extend(self.list_backups(pkg))
        
        # 按包名分组
        from collections import defaultdict
        pkg_backups = defaultdict(list)
        for b in backups:
            pkg_backups[b.package_name].append(b)
        
        for pkg, items in pkg_backups.items():
            # 按时间排序（旧的在前面）
            items.sort(key=lambda x: x.timestamp)
            
            # 保留最近 keep_count 个
            to_delete = items[:-keep_count] if len(items) > keep_count else []
            
            # 再检查保留天数
            cutoff = datetime.now() - __import__('datetime').timedelta(days=keep_days)
            cutoff_str = cutoff.strftime("%Y%m%d_%H%M%S")
            
            for item in items:
                if item in to_delete or item.timestamp < cutoff_str:
                    if self.delete_backup(item.backup_dir):
                        deleted += 1
                    else:
                        kept += 1
                else:
                    kept += 1
        
        return {'deleted': deleted, 'kept': kept}
    
    def get_total_backup_size(self) -> int:
        """获取所有备份总大小（字节）"""
        total = 0
        for backup in self.list_backups():
            total += backup.size_bytes
        return total
    
    def __repr__(self) -> str:
        return f"BackupManager(root={self.backup_root})"


if __name__ == '__main__':
    # 简单测试
    print("BackupManager 测试")
    
    backup = BackupManager()
    print(f"备份目录: {backup.backup_root}")
    print(f"总备份大小: {backup.get_total_backup_size()} bytes")
    
    # 列出所有备份
    backups = backup.list_backups()
    print(f"\n已有备份: {len(backups)}个")
    for b in backups[:5]:
        print(f"  {b.package_name} @ {b.display_time} ({b.display_size})")
