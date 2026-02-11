"""
一次性清理脚本 - 删除开发阶段的测试、调试和模拟数据文件
"""
import os
import shutil

PROJECT_ROOT = os.getcwd()

# 要删除的目录列表
DIRS_TO_REMOVE = [
    "tests/manual",
    "tools",
    "archive",
    "data/dummy"
]

def main():
    print("=" * 60)
    print("Cleaning Development Files...")
    print("=" * 60)
    
    total_removed = 0
    total_size = 0
    
    for dir_path in DIRS_TO_REMOVE:
        full_path = os.path.join(PROJECT_ROOT, dir_path)
        
        if not os.path.exists(full_path):
            print(f"\n[SKIP] {dir_path} - Not found")
            continue
        
        # 计算目录大小
        dir_size = 0
        file_count = 0
        try:
            for root, dirs, files in os.walk(full_path):
                for f in files:
                    fp = os.path.join(root, f)
                    dir_size += os.path.getsize(fp)
                    file_count += 1
        except Exception as e:
            print(f"[WARN] Could not calculate size for {dir_path}: {e}")
        
        print(f"\n[DELETE] {dir_path} ({file_count} files, {dir_size/1024:.1f} KB)")
        
        # 删除目录
        try:
            shutil.rmtree(full_path)
            print(f"  -> Successfully removed")
            total_removed += 1
            total_size += dir_size
        except Exception as e:
            print(f"  -> Failed: {e}")
    
    print("\n" + "=" * 60)
    print(f"Cleanup complete!")
    print(f"Removed {total_removed} directories, freed {total_size/1024:.1f} KB")
    print("=" * 60)

if __name__ == "__main__":
    main()
