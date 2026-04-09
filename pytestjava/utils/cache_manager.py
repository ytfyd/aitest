"""
智能缓存管理器模块
用于缓存Java AST解析结果，避免重复解析未变更的文件
支持基于内容哈希的缓存验证和LRU淘汰策略
"""

import json
import hashlib
import os
import time
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    file_hash: str
    data: Dict[str, Any]
    created_at: float
    accessed_at: float
    size_bytes: int


class CacheManager:
    """智能缓存管理器
    
    功能：
    - 基于文件内容MD5哈希的缓存键生成
    - 支持TTL（生存时间）自动过期
    - LRU（最近最少使用）淘汰策略
    - 线程安全的并发访问
    - 缓存命中率统计
    """
    
    def __init__(self, 
                 cache_dir: str = ".jcci_cache",
                 max_size_mb: int = 500,
                 ttl_hours: int = 24,
                 enabled: bool = True):
        self.cache_dir = Path(cache_dir)
        self.max_size_bytes = max_size_mb * 1024 * 1024  # 转换为字节
        self.ttl_seconds = ttl_hours * 3600
        self.enabled = enabled
        
        # 统计信息
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'errors': 0
        }
        
        # 线程锁保证并发安全
        self._lock = threading.Lock()
        
        # 初始化缓存目录
        if self.enabled:
            self._init_cache_dir()
    
    def _init_cache_dir(self):
        """初始化缓存目录"""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"[CacheManager] 缓存目录: {self.cache_dir.absolute()}")
        except Exception as e:
            logger.warning(f"[CacheManager] 无法创建缓存目录 {self.cache_dir}: {e}")
            self.enabled = False
    
    def _get_file_hash(self, file_path: str) -> str:
        """计算文件内容的MD5哈希值"""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            return hashlib.md5(content).hexdigest()
        except Exception as e:
            logger.error(f"[CacheManager] 计算文件哈希失败 {file_path}: {e}")
            return ""
    
    def get_cache_key(self, file_path: str) -> str:
        """获取缓存键（基于文件路径的简化版本）"""
        path_obj = Path(file_path)
        # 使用相对路径作为基础，避免绝对路径变化导致缓存失效
        relative_name = path_obj.name
        parent_hash = hashlib.md5(str(path_obj.parent).encode()).hexdigest()[:8]
        return f"{parent_hash}_{relative_name}"
    
    def get(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        从缓存获取解析结果
        
        参数:
            file_path: Java文件路径
            
        返回:
            缓存的解析结果字典，如果未命中返回None
        """
        if not self.enabled:
            return None
        
        with self._lock:
            try:
                # 验证文件是否存在且未变更
                current_hash = self._get_file_hash(file_path)
                if not current_hash:
                    self.stats['misses'] += 1
                    return None
                
                cache_key = self.get_cache_key(file_path)
                cache_file = self.cache_dir / f"{cache_key}.json"
                meta_file = self.cache_dir / f"{cache_key}.meta"
                
                # 检查缓存文件是否存在
                if not cache_file.exists() or not meta_file.exists():
                    self.stats['misses'] += 1
                    return None
                
                # 读取元数据验证有效性
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                
                # 检查TTL是否过期
                age_seconds = time.time() - meta.get('created_at', 0)
                if age_seconds > self.ttl_seconds:
                    logger.debug(f"[CacheManager] 缓存过期: {cache_key} (年龄: {age_seconds/3600:.1f}小时)")
                    self._remove_cache_files(cache_key)
                    self.stats['misses'] += 1
                    return None
                
                # 验证文件内容是否变更（核心机制）
                cached_hash = meta.get('file_hash', '')
                if cached_hash != current_hash:
                    logger.debug(f"[CacheManager] 文件已变更，缓存失效: {cache_key}")
                    self._remove_cache_files(cache_key)
                    self.stats['misses'] += 1
                    return None
                
                # 缓存命中，读取数据
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 更新访问时间
                meta['accessed_at'] = time.time()
                with open(meta_file, 'w', encoding='utf-8') as f:
                    json.dump(meta, f, ensure_ascii=False)
                
                self.stats['hits'] += 1
                
                if self.stats['hits'] % 50 == 0:  # 每50次命中输出一次日志
                    hit_rate = self.get_hit_rate()
                    logger.info(f"[CacheManager] 缓存统计: 命中率={hit_rate:.1%}, "
                               f"命中={self.stats['hits']}, 未命中={self.stats['misses']}")
                
                return data
                
            except Exception as e:
                logger.error(f"[CacheManager] 读取缓存失败: {e}")
                self.stats['errors'] += 1
                self.stats['misses'] += 1
                return None
    
    def set(self, file_path: str, data: Dict[str, Any]) -> bool:
        """
        将解析结果保存到缓存
        
        参数:
            file_path: Java文件路径
            data: 解析结果数据
            
        返回:
            是否保存成功
        """
        if not self.enabled:
            return False
        
        with self._lock:
            try:
                # 计算当前文件哈希
                current_hash = self._get_file_hash(file_path)
                if not current_hash:
                    return False
                
                cache_key = self.get_cache_key(file_path)
                cache_file = self.cache_dir / f"{cache_key}.json"
                meta_file = self.cache_dir / f"{cache_key}.meta"
                
                # 检查缓存大小限制
                self._check_and_evict_if_needed(len(json.dumps(data)))
                
                # 保存数据
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                # 保存元数据
                meta = {
                    'file_hash': current_hash,
                    'file_path': str(file_path),
                    'created_at': time.time(),
                    'accessed_at': time.time(),
                    'size_bytes': len(json.dumps(data))
                }
                
                with open(meta_file, 'w', encoding='utf-8') as f:
                    json.dump(meta, f, ensure_ascii=False)
                
                logger.debug(f"[CacheManager] 已缓存: {cache_key}")
                return True
                
            except Exception as e:
                logger.error(f"[CacheManager] 保存缓存失败: {e}")
                self.stats['errors'] += 1
                return False
    
    def _remove_cache_files(self, cache_key: str):
        """删除指定的缓存文件"""
        try:
            cache_file = self.cache_dir / f"{cache_key}.json"
            meta_file = self.cache_dir / f"{cache_key}.meta"
            
            if cache_file.exists():
                cache_file.unlink()
            if meta_file.exists():
                meta_file.unlink()
        except Exception as e:
            logger.warning(f"[CacheManager] 删除缓存文件失败: {e}")
    
    def _check_and_evict_if_needed(self, new_item_size: int):
        """检查缓存大小并在需要时执行LRU淘汰"""
        try:
            total_size = sum(
                f.stat().st_size 
                for f in self.cache_dir.glob("*.json")
            )
            
            # 如果添加新项后超过限制，执行淘汰
            while (total_size + new_item_size) > self.max_size_bytes and self.max_size_bytes > 0:
                oldest_entry = self._find_oldest_entry()
                if not oldest_entry:
                    break
                
                self._remove_cache_files(oldest_entry)
                self.stats['evictions'] += 1
                
                # 重新计算总大小
                total_size = sum(
                    f.stat().st_size 
                    for f in self.cache_dir.glob("*.json")
                )
                
                if self.stats['evictions'] % 10 == 0:
                    logger.info(f"[CacheManager] LRU淘汰: 已清理 {self.stats['evictions']} 个缓存项")
                    
        except Exception as e:
            logger.error(f"[CacheManager] 缓存大小检查失败: {e}")
    
    def _find_oldest_entry(self) -> Optional[str]:
        """找到最久未访问的缓存条目"""
        oldest_key = None
        oldest_time = float('inf')
        
        for meta_file in self.cache_dir.glob("*.meta"):
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                
                accessed_at = meta.get('accessed_at', 0)
                if accessed_at < oldest_time:
                    oldest_time = accessed_at
                    oldest_key = meta_file.stem
                    
            except Exception:
                continue
        
        return oldest_key
    
    def invalidate(self, file_path: str = None):
        """
        使缓存失效
        
        参数:
            file_path: 指定文件的缓存失效，如果为None则清空所有缓存
        """
        with self._lock:
            try:
                if file_path:
                    cache_key = self.get_cache_key(file_path)
                    self._remove_cache_files(cache_key)
                    logger.debug(f"[CacheManager] 已使缓存失效: {file_path}")
                else:
                    # 清空所有缓存
                    for cache_file in list(self.cache_dir.glob("*.json")):
                        cache_file.unlink()
                    for meta_file in list(self.cache_dir.glob("*.meta")):
                        meta_file.unlink()
                    
                    logger.info("[CacheManager] 已清空所有缓存")
                    self.stats = {'hits': 0, 'misses': 0, 'evictions': 0, 'errors': 0}
                    
            except Exception as e:
                logger.error(f"[CacheManager] 缓存失效操作失败: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_requests = self.stats['hits'] + self.stats['misses']
        
        # 计算实际缓存大小
        cache_size_bytes = sum(
            f.stat().st_size 
            for f in self.cache_dir.glob("*.json")
        ) if self.cache_dir.exists() else 0
        
        cache_count = len(list(self.cache_dir.glob("*.json"))) if self.cache_dir.exists() else 0
        
        return {
            **self.stats,
            'hit_rate': self.get_hit_rate(),
            'total_requests': total_requests,
            'cache_count': cache_count,
            'cache_size_mb': cache_size_bytes / (1024 * 1024),
            'cache_dir': str(self.cache_dir),
            'enabled': self.enabled,
            'ttl_hours': self.ttl_seconds / 3600,
            'max_size_mb': self.max_size_bytes / (1024 * 1024)
        }
    
    def get_hit_rate(self) -> float:
        """计算缓存命中率"""
        total = self.stats['hits'] + self.stats['misses']
        if total == 0:
            return 0.0
        return self.stats['hits'] / total
    
    def clear_expired(self) -> int:
        """清除所有过期的缓存条目"""
        expired_count = 0
        
        if not self.cache_dir.exists():
            return 0
        
        for meta_file in self.cache_dir.glob("*.meta"):
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                
                created_at = meta.get('created_at', 0)
                age_seconds = time.time() - created_at
                
                if age_seconds > self.ttl_seconds:
                    cache_key = meta_file.stem
                    self._remove_cache_files(cache_key)
                    expired_count += 1
                    
            except Exception:
                continue
        
        if expired_count > 0:
            logger.info(f"[CacheManager] 已清除 {expired_count} 个过期缓存项")
        
        return expired_count
    
    def print_report(self):
        """打印详细的缓存性能报告"""
        stats = self.get_stats()
        
        logger.info("=" * 70)
        logger.info("📊 CacheManager 性能报告")
        logger.info("=" * 70)
        logger.info(f"  状态: {'✅ 启用' if stats['enabled'] else '❌ 禁用'}")
        logger.info(f"  缓存目录: {stats['cache_dir']}")
        logger.info(f"  TTL有效期: {stats['ttl_hours']:.1f} 小时")
        logger.info(f"  最大容量: {stats['max_size_mb']:.1f} MB")
        logger.info("-" * 70)
        logger.info(f"  总请求数: {stats['total_requests']}")
        logger.info(f"  ✅ 缓存命中: {stats['hits']} ({stats['hit_rate']:.1%})")
        logger.info(f"  ❌ 缓存未命中: {stats['misses']}")
        logger.info(f"  🗑️  LRU淘汰次数: {stats['evictions']}")
        logger.info(f"  ⚠️  错误次数: {stats['errors']}")
        logger.info("-" * 70)
        logger.info(f"  当前缓存项数: {stats['cache_count']}")
        logger.info(f"  当前占用空间: {stats['cache_size_mb']:.2f} MB / {stats['max_size_mb']:.1f} MB "
                   f"({stats['cache_size_mb']/stats['max_size_mb']*100:.1f}%)" if stats['max_size_mb'] > 0 else "")
        logger.info("=" * 70)


# 全局单例实例
_global_cache_manager: Optional[CacheManager] = None


def get_cache_manager(cache_dir: str = ".jcci_cache", **kwargs) -> CacheManager:
    """获取全局缓存管理器单例"""
    global _global_cache_manager
    
    if _global_cache_manager is None:
        _global_cache_manager = CacheManager(cache_dir=cache_dir, **kwargs)
    
    return _global_cache_manager


def reset_cache_manager():
    """重置全局缓存管理器（用于测试）"""
    global _global_cache_manager
    if _global_cache_manager:
        _global_cache_manager.invalidate()
    _global_cache_manager = None
