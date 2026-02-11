"""
Quant Data Bridge - System Cache Cleaner
清理项目缓存文件，包括 __pycache__、.pyc、.log 等临时文件
"""
import os
import shutil
import glob
from pathlib import Path

PROJECT_ROOT = os.getcwd()

# 目录豁免列表（不扫描这些目录）
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '.idea', '.vscode', 'build', 'dist'}

def clean_pycache():
    """清理所有 __pycache__ 目录"""
    print("\n[1] Cleaning __pycache__ directories...")
    count = 0
    
    for root, dirs, files in os.walk(PROJECT_ROOT):
        # 跳过豁免目录
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        
        if '__pycache__' in dirs:
            cache_path = os.path.join(root, '__pycache__')
            try:
                shutil.rmtree(cache_path)
                print(f"  [OK] Deleted: {os.path.relpath(cache_path, PROJECT_ROOT)}")
                count += 1
            except Exception as e:
                print(f"  [FAIL] Failed: {cache_path} ({e})")
    
    print(f"  -> Total: {count} __pycache__ directories removed")

def clean_pyc_files():
    """清理所有 .pyc 文件"""
    print("\n[2] Cleaning .pyc files...")
    count = 0
    
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        
        for file in files:
            if file.endswith('.pyc'):
                file_path = os.path.join(root, file)
                try:
                    os.remove(file_path)
                    print(f"  [OK] Deleted: {os.path.relpath(file_path, PROJECT_ROOT)}")
                    count += 1
                except Exception as e:
                    print(f"  [FAIL] Failed: {file_path} ({e})")
    
    print(f"  -> Total: {count} .pyc files removed")

def clean_log_files():
    """清理根目录的日志文件"""
    print("\n[3] Cleaning log files...")
    count = 0
    
    log_patterns = ['*.log', '*.log.*']
    for pattern in log_patterns:
        for log_file in glob.glob(os.path.join(PROJECT_ROOT, pattern)):
            try:
                os.remove(log_file)
                print(f"  [OK] Deleted: {os.path.basename(log_file)}")
                count += 1
            except Exception as e:
                print(f"  [FAIL] Failed: {log_file} ({e})")
    
    print(f"  -> Total: {count} log files removed")

def clean_build_artifacts():
    """清理编译产物和临时构建文件"""
    print("\n[4] Cleaning build artifacts...")
    count = 0
    
    # PyInstaller 临时文件
    build_patterns = ['build', '*.egg-info']
    for pattern in build_patterns:
        for item in glob.glob(os.path.join(PROJECT_ROOT, pattern)):
            if os.path.isdir(item):
                try:
                    shutil.rmtree(item)
                    print(f"  [OK] Deleted: {os.path.basename(item)}/")
                    count += 1
                except Exception as e:
                    print(f"  [FAIL] Failed: {item} ({e})")
    
    print(f"  -> Total: {count} build artifacts removed")

def get_cache_size():
    """估算被清理的缓存总大小（近似值）"""
    total_size = 0
    
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        
        if '__pycache__' in dirs:
            cache_path = os.path.join(root, '__pycache__')
            for f in os.listdir(cache_path):
                fp = os.path.join(cache_path, f)
                if os.path.isfile(fp):
                    total_size += os.path.getsize(fp)
        
        for file in files:
            if file.endswith(('.pyc', '.log')):
                total_size += os.path.getsize(os.path.join(root, file))
    
    return total_size / 1024  # KB

def main():
    print("=" * 60)
    print("Quant Data Bridge - System Cache Cleaner")
    print("=" * 60)
    
    # 预估大小
    estimated_size = get_cache_size()
    print(f"\nEstimated cache size: {estimated_size:.2f} KB")
    
    # 执行清理
    clean_pycache()
    clean_pyc_files()
    clean_log_files()
    clean_build_artifacts()
    
    print("\n" + "=" * 60)
    print("Cache cleanup complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()