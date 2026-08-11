from pathlib import Path
p = Path('tools/assets/designlib.py')
txt = p.read_text(encoding='utf-8')
head = txt.find('FRAMEWORK_CODE = """')
body_start = head + len('FRAMEWORK_CODE = """')
positions = []
cur = body_start
for _ in range(10):
    nx = txt.find('"""', cur)
    if nx < 0:
        break
    positions.append(nx)
    cur = nx + 3
print("First 10 triple-quote positions after FRAMEWORK_CODE start:")
for i, pos in enumerate(positions):
    context = txt[max(0, pos-35):pos+35]
    print(f"  #{i} pos={pos} around={context!r}")
