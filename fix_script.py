import re

with open("backend/tests/t19_generator.py", "r", encoding="utf-8") as f:
    text = f.read()

text = re.sub(
    r'service_duration_source="fixed",\s+fixed_duration_minutes=\d+,',
    r'service_duration_source="work_norm",',
    text
)

with open("backend/tests/t19_generator.py", "w", encoding="utf-8") as f:
    f.write(text)
