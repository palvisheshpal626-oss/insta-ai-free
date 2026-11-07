import re

with open('chatgpt_dump.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Find all buttons around prompt-textarea
pos = html.find('id="prompt-textarea"')
print("prompt-textarea pos:", pos)
if pos != -1:
    slice_around = html[pos-500:pos+2500]
    for b in re.finditer(r'<button([^>]+)>', slice_around):
        print("Button near prompt:", b.group(1))

# Check any button with svg or arrow
print("\nButtons with aria-label or title:")
for b in re.finditer(r'<button[^>]*?(aria-label|title|data-testid)=["\']([^"\']+)["\'][^>]*>', html):
    print(" ", b.group(0)[:150])
