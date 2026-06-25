#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
InstallManager — 安装策略管理器

职责：
- 多种安装方式封装（覆盖安装 / 卸载重装 / Split APK 安装）
- 安装结果解析与分类（成功 / 签名冲突 / 版本降级 / 其他错误）
- 安装错误码映射与归因
- 安装日志记录

设计约束：
- 不依赖 GUI，可被独立测试
- 所有安装结果必须分类，签名冲突需明确标记为预期拒绝
- 支持 Split APK 的 install-multiple
"""

import re
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Union
from datetime import datetime


@dataclass
class InstallResult:
    """安装结果"""
    success: bool
    status: str  # 'success' | 'signature_conflict' | 'version_downgrade' | 'invalid_apk' | 'other'
    code: str = ""  # 原始错误码
    message: str = ""  # 人类可读的消息
    suggestion: str = ""  # 建议操作
    raw_output: str = ""  # 原始 ADB 输出


@dataclass
class InstallLog:
    """安装日志记录"""
    timestamp: str
    package: str
    apk_path: str
    strategy: str
    result: InstallResult
    device_serial: str = ""


class InstallError(Exception):
    """安装操作错误"""
    pass


class InstallManager:
    """
    安装策略管理器
    
    使用示例:
        from adb_manager import ADBManager
        from install_manager import InstallManager
        
        adb = ADBManager()
        adb.select_device('abc123')
        
        install = InstallManager(adb)
        
        # 覆盖安装
        result = install.install_overwrite('/path/to/resigned.apk')
        
        if result.status == 'signature_conflict':
            print("✓ 签名验证拒绝正常")
        
        # 卸载后安装
        result = install.install_uninstall_then_install('com.example.app', '/path/to/resigned.apk')
    """
    
    # 安装错误码映射表
    ERROR_CODES = {
        'INSTALL_FAILED_ALREADY_EXISTS': {
            'status': 'other',
            'message': '应用已存在',
            'suggestion': '使用 -r 参数覆盖安装'
        },
        'INSTALL_FAILED_INVALID_APK': {
            'status': 'invalid_apk',
            'message': 'APK 文件无效或损坏',
            'suggestion': '检查 APK 签名和 zipalign 对齐'
        },
        'INSTALL_FAILED_INVALID_URI': {
            'status': 'other',
            'message': 'APK 路径无效',
            'suggestion': '检查 APK 文件是否存在'
        },
        'INSTALL_FAILED_INSUFFICIENT_STORAGE': {
            'status': 'other',
            'message': '设备存储空间不足',
            'suggestion': '清理设备存储空间'
        },
        'INSTALL_FAILED_DUPLICATE_PACKAGE': {
            'status': 'other',
            'message': '包名冲突',
            'suggestion': '应用已存在但签名不同，先卸载再安装'
        },
        'INSTALL_FAILED_NO_SHARED_USER': {
            'status': 'other',
            'message': '共享用户不存在',
            'suggestion': '检查应用依赖'
        },
        'INSTALL_FAILED_UPDATE_INCOMPATIBLE': {
            'status': 'signature_conflict',
            'message': '签名不匹配，安装被拒绝',
            'suggestion': '这是预期行为！签名验证机制工作正常。'
        },
        'INSTALL_FAILED_SHARED_USER_INCOMPATIBLE': {
            'status': 'signature_conflict',
            'message': '共享用户签名不匹配',
            'suggestion': '签名验证拒绝正常'
        },
        'INSTALL_FAILED_MISSING_SHARED_LIBRARY': {
            'status': 'other',
            'message': '缺少共享库',
            'suggestion': '检查设备是否支持该应用'
        },
        'INSTALL_FAILED_REPLACE_COULDNT_DELETE': {
            'status': 'other',
            'message': '无法删除旧版本',
            'suggestion': '尝试卸载后安装'
        },
        'INSTALL_FAILED_DEXOPT': {
            'status': 'other',
            'message': 'DEX 优化失败',
            'suggestion': '设备空间不足或系统错误'
        },
        'INSTALL_FAILED_OLDER_SDK': {
            'status': 'other',
            'message': 'SDK 版本过低',
            'suggestion': '设备系统版本太旧'
        },
        'INSTALL_FAILED_CONFLICTING_PROVIDER': {
            'status': 'other',
            'message': 'ContentProvider 冲突',
            'suggestion': '应用与已安装应用有冲突'
        },
        'INSTALL_FAILED_NEWER_SDK': {
            'status': 'other',
            'message': 'SDK 版本过高',
            'suggestion': '设备系统版本太旧'
        },
        'INSTALL_FAILED_TEST_ONLY': {
            'status': 'other',
            'message': '测试应用不允许安装',
            'suggestion': '使用 -t 参数允许测试包'
        },
        'INSTALL_FAILED_CPU_ABI_INCOMPATIBLE': {
            'status': 'other',
            'message': 'CPU 架构不兼容',
            'suggestion': '检查设备架构是否支持'
        },
        'INSTALL_FAILED_MISSING_FEATURE': {
            'status': 'other',
            'message': '缺少硬件特性',
            'suggestion': '检查设备是否支持该应用所需特性'
        },
        'INSTALL_FAILED_CONTAINER_ERROR': {
            'status': 'other',
            'message': 'SD 卡容器错误',
            'suggestion': '检查 SD 卡状态'
        },
        'INSTALL_FAILED_INVALID_INSTALL_LOCATION': {
            'status': 'other',
            'message': '安装位置无效',
            'suggestion': '使用默认安装位置'
        },
        'INSTALL_FAILED_MEDIA_UNAVAILABLE': {
            'status': 'other',
            'message': '媒体不可用',
            'suggestion': '检查存储设备状态'
        },
        'INSTALL_FAILED_VERIFICATION_TIMEOUT': {
            'status': 'other',
            'message': '验证超时',
            'suggestion': '网络问题或验证服务器不可用'
        },
        'INSTALL_FAILED_VERIFICATION_FAILURE': {
            'status': 'other',
            'message': '验证失败',
            'suggestion': 'APK 验证未通过，可能被篡改'
        },
        'INSTALL_FAILED_PACKAGE_CHANGED': {
            'status': 'other',
            'message': '包已改变',
            'suggestion': 'APK 与预期不符'
        },
        'INSTALL_FAILED_UID_CHANGED': {
            'status': 'other',
            'message': 'UID 改变',
            'suggestion': '系统异常，重启设备后重试'
        },
        'INSTALL_FAILED_VERSION_DOWNGRADE': {
            'status': 'version_downgrade',
            'message': '版本降级',
            'suggestion': '使用 -d 参数允许降级，或卸载后安装'
        },
        'INSTALL_FAILED_PERMISSION_MODEL_DOWNGRADE': {
            'status': 'other',
            'message': '权限模型降级',
            'suggestion': '新版本使用旧权限模型'
        },
        'INSTALL_FAILED_PARSE_NOT_APK': {
            'status': 'invalid_apk',
            'message': '不是有效的 APK 文件',
            'suggestion': '检查文件是否为 APK'
        },
        'INSTALL_FAILED_PARSE_BAD_MANIFEST': {
            'status': 'invalid_apk',
            'message': 'AndroidManifest.xml 解析错误',
            'suggestion': 'APK 可能已损坏'
        },
        'INSTALL_FAILED_PARSE_UNEXPECTED_EXCEPTION': {
            'status': 'invalid_apk',
            'message': '解析异常',
            'suggestion': 'APK 文件损坏或不完整'
        },
        'INSTALL_FAILED_PARSE_NO_CERTIFICATES': {
            'status': 'invalid_apk',
            'message': 'APK 没有签名证书',
            'suggestion': 'APK 未正确签名，检查签名步骤'
        },
        'INSTALL_FAILED_PARSE_INCONSISTENT_CERTIFICATES': {
            'status': 'signature_conflict',
            'message': '证书不一致',
            'suggestion': '签名验证拒绝正常'
        },
        'INSTALL_FAILED_INTERNAL_ERROR': {
            'status': 'other',
            'message': '内部错误',
            'suggestion': '系统异常，重启设备后重试'
        },
    }
    
    def __init__(self, tools, logger=None):
        """
        初始化安装管理器
        
        Args:
            adb_manager: ADBManager 实例
            logger: 可选的日志回调函数，签名: logger(cmd_list, stdout, stderr, returncode)
        """
        self.adb = adb_manager
        self.logger = logger
        self._logs: List[InstallLog] = []
    
    # ═══════════════════════════════════════════════════
    # 安装策略
    # ═══════════════════════════════════════════════════
    
    def install_overwrite(
        self,
        apk_path: Union[str, Path],
        splits: Optional[List[str]] = None
    ) -> InstallResult:
        """
        直接覆盖安装（保留数据）
        
        命令: adb install -r -d -t <apk>
        Split: adb install-multiple -r -d -t base.apk split1.apk ...
        
        Args:
            apk_path: APK 文件路径
            splits: Split APK 路径列表（可选）
        
        Returns:
            InstallResult
        """
        apk_path = Path(apk_path)
        if not apk_path.exists():
            return InstallResult(
                success=False,
                status='other',
                message=f'APK 文件不存在: {apk_path}'
            )
        
        try:
            if splits and len(splits) > 0:
                # Split APK 安装
                # _install_multiple 已经返回 InstallResult，直接返回
                return self._install_multiple(apk_path, splits, reinstall=True)
            else:
                # 单 APK 安装
                result = self._run_install(['install', '-r', '-d', '-t', str(apk_path)])
                return self._parse_result(result, 'overwrite', str(apk_path))
        
        except Exception as e:
            return InstallResult(
                success=False,
                status='other',
                message=f'安装异常: {str(e)}'
            )
    
    def install_uninstall_then_install(
        self,
        package_name: str,
        apk_path: Union[str, Path]
    ) -> InstallResult:
        """
        卸载原应用后安装（清除数据）
        
        命令: adb uninstall <pkg> && adb install <apk>
        
        Args:
            package_name: 应用包名
            apk_path: APK 文件路径
        
        Returns:
            InstallResult
        """
        apk_path = Path(apk_path)
        if not apk_path.exists():
            return InstallResult(
                success=False,
                status='other',
                message=f'APK 文件不存在: {apk_path}'
            )
        
        try:
            # 1. 卸载
            uninstall_result = self._run_adb(['uninstall', package_name])
            if uninstall_result[0] != 0 and 'Success' not in uninstall_result[1]:
                # 卸载失败但继续尝试安装
                pass
            
            # 2. 安装
            install_result = self._run_install(['install', str(apk_path)])
            
            return self._parse_result(install_result, 'uninstall_then_install', str(apk_path))
        
        except Exception as e:
            return InstallResult(
                success=False,
                status='other',
                message=f'安装异常: {str(e)}'
            )
    
    def install_split_apk(
        self,
        base_apk: Union[str, Path],
        split_apks: List[str]
    ) -> InstallResult:
        """
        Split APK 安装（显式方法）
        
        命令: adb install-multiple -r -d -t base.apk split1.apk ...
        
        Args:
            base_apk: base APK 路径
            split_apks: Split APK 路径列表
        
        Returns:
            InstallResult
        """
        return self._install_multiple(base_apk, split_apks, reinstall=True)
    
    def install_multiple(self, base_apk: str, split_apks: list[str], reinstall: bool = True) -> tuple[bool, str]:
        """
        Split APK 多文件安装（对外接口）
        
        命令: adb install-multiple -r -d -t base.apk split1.apk ...
        
        Args:
            base_apk: base APK 路径
            split_apks: Split APK 路径列表
            reinstall: 是否覆盖安装
        
        Returns:
            (success, message)
        """
        result = self._install_multiple(base_apk, split_apks, reinstall)
        return result.success, result.message
    
    def _install_multiple(
        self,
        base_apk: Union[str, Path],
        split_apks: List[str],
        reinstall: bool = True
    ) -> InstallResult:
        """
        执行 install-multiple
        """
        base_apk = Path(base_apk)
        if not base_apk.exists():
            return InstallResult(
                success=False,
                status='other',
                message=f'base APK 不存在: {base_apk}'
            )
        
        # 构建命令
        cmd = ['install-multiple']
        if reinstall:
            cmd.extend(['-r', '-d', '-t'])
        
        cmd.append(str(base_apk))
        for split in split_apks:
            split_path = Path(split)
            if split_path.exists():
                cmd.append(str(split_path))
        
        result = self._run_install(cmd)
        return self._parse_result(result, 'install_multiple', str(base_apk))
    
    # ═══════════════════════════════════════════════════
    # 结果解析
    # ═══════════════════════════════════════════════════
    
    def analyze_error(self, error_output: str) -> Dict[str, str]:
        """
        解析安装错误输出
        
        Args:
            error_output: ADB 安装命令的错误输出
        
        Returns:
            Dict: {status, code, message, suggestion, is_expected_rejection}
        """
        # 1. 尝试匹配已知错误码
        for error_code, info in self.ERROR_CODES.items():
            if error_code in error_output:
                return {
                    'status': info['status'],
                    'code': error_code,
                    'message': info['message'],
                    'suggestion': info['suggestion'],
                    'is_expected_rejection': info['status'] == 'signature_conflict'
                }
        
        # 2. 通用匹配
        if 'Failure' in error_output:
            # 提取 Failure 后的内容
            match = re.search(r'Failure\s*\[([^\]]+)\]', error_output)
            if match:
                error_text = match.group(1)
                return {
                    'status': 'other',
                    'code': error_text,
                    'message': f'安装失败: {error_text}',
                    'suggestion': '未知错误，请查看日志',
                    'is_expected_rejection': False
                }
        
        # 3. 成功
        if 'Success' in error_output:
            return {
                'status': 'success',
                'code': 'SUCCESS',
                'message': '安装成功',
                'suggestion': '',
                'is_expected_rejection': False
            }
        
        # 4. 无法解析
        return {
            'status': 'other',
            'code': 'UNKNOWN',
            'message': f'未知错误: {error_output[:200]}',
            'suggestion': '请检查 ADB 日志',
            'is_expected_rejection': False
        }
    
    def _parse_result(
        self,
        adb_result: Tuple[int, str, str],
        strategy: str,
        apk_path: str
    ) -> InstallResult:
        """
        解析 ADB 安装结果
        """
        returncode, stdout, stderr = adb_result
        output = stdout + stderr
        
        # 分析错误
        analysis = self.analyze_error(output)
        
        # 构建结果
        result = InstallResult(
            success=analysis['status'] == 'success',
            status=analysis['status'],
            code=analysis['code'],
            message=analysis['message'],
            suggestion=analysis['suggestion'],
            raw_output=output
        )
        
        # 记录日志
        self._log_install(strategy, apk_path, result)
        
        return result
    
    # ═══════════════════════════════════════════════════
    # 日志管理
    # ═══════════════════════════════════════════════════
    
    def _log_install(self, strategy: str, apk_path: str, result: InstallResult):
        """记录安装日志"""
        log = InstallLog(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            package=Path(apk_path).stem,
            apk_path=apk_path,
            strategy=strategy,
            result=result,
            device_serial=getattr(self.adb, 'selected_device', '')
        )
        self._logs.append(log)
    
    def get_logs(
        self,
        package: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[InstallLog]:
        """
        获取安装日志
        
        Args:
            package: 过滤指定包名
            status: 过滤指定状态
        
        Returns:
            List[InstallLog]
        """
        logs = self._logs
        
        if package:
            logs = [l for l in logs if l.package == package]
        
        if status:
            logs = [l for l in logs if l.result.status == status]
        
        return logs
    
    def get_signature_conflict_count(self) -> int:
        """获取签名冲突次数（预期拒绝）"""
        return len([l for l in self._logs if l.result.status == 'signature_conflict'])
    
    def get_success_count(self) -> int:
        """获取成功安装次数"""
        return len([l for l in self._logs if l.result.status == 'success'])
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        stats = {
            'total': len(self._logs),
            'success': 0,
            'signature_conflict': 0,
            'version_downgrade': 0,
            'invalid_apk': 0,
            'other': 0
        }
        
        for log in self._logs:
            status = log.result.status
            if status in stats:
                stats[status] += 1
            else:
                stats['other'] += 1
        
        return stats
    
    def export_logs(self, path: Union[str, Path]) -> bool:
        """导出日志到 JSON 文件"""
        try:
            path = Path(path)
            data = []
            for log in self._logs:
                data.append({
                    'timestamp': log.timestamp,
                    'package': log.package,
                    'apk_path': log.apk_path,
                    'strategy': log.strategy,
                    'device_serial': log.device_serial,
                    'result': {
                        'success': log.result.success,
                        'status': log.result.status,
                        'code': log.result.code,
                        'message': log.result.message,
                        'suggestion': log.result.suggestion
                    }
                })
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception:
            return False
    
    # ═══════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════
    
    def _run_install(self, cmd: List[str]) -> Tuple[int, str, str]:
        """执行安装命令，自动处理 abb_exec streaming 错误"""
        return self._run_adb(cmd, is_install=True)
    
    def _run_adb(self, cmd: List[str], is_install: bool = False) -> Tuple[int, str, str]:
        """执行 ADB 命令，支持安装错误自动降级重试"""
        if hasattr(self.adb, '_run'):
            result = self.adb._run(cmd)
            
            # 安装命令：检测 abb_exec / streaming 错误并自动降级重试
            if is_install and result[0] != 0:
                output = result[1] + result[2]
                if any(err in output for err in ['abb_exec', 'closed', 'streamed', 'incremental']):
                    # 自动重试：添加 --no-incremental 参数
                    retry_cmd = self._add_no_incremental(cmd)
                    if retry_cmd != cmd:
                        result = self.adb._run(retry_cmd)
            
            # 记录到命令日志面板
            if self.logger:
                self.logger(cmd, result[1], result[2], result[0])
            
            return result
        else:
            raise InstallError("ADBManager 未提供 _run 方法")
    
    def _add_no_incremental(self, cmd: List[str]) -> List[str]:
        """在安装命令中添加 --no-incremental 参数"""
        if 'install' not in cmd:
            return cmd
        
        # 查找 install 或 install-multiple 的位置
        new_cmd = []
        for i, arg in enumerate(cmd):
            if arg in ('install', 'install-multiple') and i + 1 < len(cmd):
                new_cmd.append(arg)
                new_cmd.append('--no-incremental')
            else:
                new_cmd.append(arg)
        return new_cmd
    
    def __repr__(self) -> str:
        return f"InstallManager(adb={self.adb}, logs={len(self._logs)})"


if __name__ == '__main__':
    # 简单测试
    print("InstallManager 测试")
    print(f"\n已定义错误码: {len(InstallManager.ERROR_CODES)}个")
    
    # 测试错误解析
    test_cases = [
        "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]",
        "Failure [INSTALL_FAILED_INVALID_APK]",
        "Failure [INSTALL_FAILED_VERSION_DOWNGRADE]",
        "Success",
        "Failure [INSTALL_FAILED_NO_CERTIFICATES]",
    ]
    
    print("\n错误解析测试:")
    for test in test_cases:
        result = InstallManager.analyze_error.__func__(None, test)
        print(f"  {test[:40]:40} -> {result['status']}")
