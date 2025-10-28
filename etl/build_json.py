from pathlib import Path
import shutil
SRC = Path("data/processed"); DST = Path("public/data/processed")
def run():
    if not SRC.exists(): return
    if DST.exists(): shutil.rmtree(DST)
    shutil.copytree(SRC, DST)
if __name__ == "__main__": run()
