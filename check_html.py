import requests
r = requests.get('http://localhost:8000/')
t = r.text
# 检查是否用了反引号模板字符串
if '`installDep(' in t:
    print('FIXED: using backtick template')
elif "installDep(\\'" in t:
    print('OLD: still using escaped quotes')
else:
    # 找到 installDep 附近的代码
    idx = t.find('installDep(')
    if idx >= 0:
        print('Context:', repr(t[idx-20:idx+80]))
    else:
        print('installDep not found')
