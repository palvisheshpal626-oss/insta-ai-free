import re

with open('chatgpt_dump.html', 'r', encoding='utf-8') as f:
    html = f.read()

print('Has data-message-author-role:', 'data-message-author-role' in html)
print('Has data-testid:', 'data-testid' in html)

testids = set()
for m in re.finditer(r'data-testid=["\']([^"\']+)["\']', html):
    val = m.group(1)
    if any(k in val.lower() for k in ['turn', 'message', 'send', 'stop', 'prompt', 'response', 'composer']):
        testids.add(val)
print("Matching testids:")
for t in sorted(testids):
    print(" ", t)

aria_labels = set()
for m in re.finditer(r'aria-label=["\']([^"\']+)["\']', html):
    val = m.group(1)
    if any(k in val.lower() for k in ['send', 'stop', 'prompt', 'message', 'submit']):
        aria_labels.add(val)
print("\nMatching aria-labels:")
for a in sorted(aria_labels):
    print(" ", a)

# Look for classes of assistant responses
classes = set()
for m in re.finditer(r'class=["\']([^"\']+)["\']', html):
    val = m.group(1)
    if any(k in val.lower() for k in ['markdown', 'prose', 'message', 'turn', 'response']):
        for c in val.split():
            if any(k in c.lower() for k in ['markdown', 'prose', 'message', 'turn', 'response']):
                classes.add(c)
print("\nMatching classes:")
for c in sorted(classes)[:20]:
    print(" ", c)
