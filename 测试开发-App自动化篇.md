# 测试开发-App自动化篇

> 对应清单：App 自动化【必须掌握（做 App 测试方向的话）】
> 对应自查：Q7（App 测试中权限弹窗怎么处理？弱网怎么模拟？）
> 立场：App 自动化的难点不在写脚本，在**环境**（设备、驱动、弹窗、弱网、稳定性）。这一篇讲的全是"脚本跑不起来"和"跑起来不稳"的那部分。

---

## 0. 先定位：App 和 Web 自动化的四个本质差异

| | Web | App |
| --- | --- | --- |
| 运行环境 | 一个浏览器，可无头 | **真机/模拟器**，有系统层 |
| 干扰因素 | 页面自身的动画/异步 | **系统弹窗、权限、来电、通知、广告** |
| 定位方式 | DOM / role / testid | 原生控件树（resource-id / accessibility id） |
| 稳定性 | 元素等不到 | 元素等不到 + 设备断开 + App 崩溃 + 被系统杀后台 |
| 调试 | DevTools / Trace | **adb logcat、截图、录屏、Inspector** |

自查分级：

| 内容 | 档位 | 说明 |
| --- | --- | --- |
| Capabilities 配置 | 熟练 | 起不来的第一原因 |
| 元素定位（resource-id/accessibility id） | 熟练 | 定位质量决定寿命 |
| 权限弹窗处理 | 熟练 | Q7 一半 |
| 弱网模拟 | 会用 | Q7 另一半 |
| logcat 抓日志与崩溃分析 | 熟练 | 失败定位必备 |
| 多机型兼容 | 会用 | 云真机 |

---

## 1. Appium 架构与启动

### 1.1 架构（理解它才知道问题出在哪一层）

```
测试代码（client） ──HTTP/W3C──▶ Appium Server ──▶ UiAutomator2 驱动（Android）/ XCUITest（iOS）──▶ 设备
```

- **Appium Server 是中间层**：把 WebDriver 协议翻译成设备能懂的动作。
- **driver 是设备上的 agent**：Android 用 `uiautomator2`（作为 APK 装在设备上），iOS 用 `WebDriverAgent`。
- **所以出问题分三层**：client 脚本问题 / Appium server 问题 / 设备与驱动问题。**日志要分层看**（`appium --log-level debug`）。

### 1.2 环境与启动

```bash
# 检查设备
adb devices                              # Android
xcrun simctl list devices               # iOS 模拟器

# 起 Appium
appium --log-level info --log appium.log
# 常用参数：--allow-insecure=adb_shell（允许 adb shell 命令）
```

```python
# conftest.py
import pytest
from appium import webdriver
from appium.options.android import UiAutomator2Options
from selenium.webdriver.common.by import By

APPIUM_URL = "http://127.0.0.1:4723"


@pytest.fixture(scope="session")
def driver():
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.device_name = "emulator-5554"          # adb devices 里的名字
    options.app_package = "com.example.app"
    options.app_activity = "com.example.app.MainActivity"
    options.no_reset = False                        # 每条会话重置 App 状态
    options.set_capability("autoGrantPermissions", True)     # 自动授权（见 Q7）
    options.set_capability("newCommandTimeout", 300)
    options.set_capability("uiautomator2ServerLaunchTimeout", 60000)

    drv = webdriver.Remote(APPIUM_URL, options=options)
    drv.implicitly_wait(0)                          # 不要用隐式等待，用显式
    yield drv
    drv.quit()
```

### 1.3 Capabilities 里最关键的几个（起不来先看这里）

| 能力 | 作用 | 坑 |
| --- | --- | --- |
| `platformName` / `deviceName` | 目标平台和设备 | `deviceName` 写错 → 设备找不到 |
| `appPackage` / `appActivity` | 启动哪个 App | `appActivity` 要全路径，写错直接崩 |
| `noReset` | 是否保留 App 数据 | `True` 时登录态保留但脏数据也保留 |
| `fullReset` | 卸载重装 | 慢，但最干净 |
| `autoGrantPermissions` | 安装时自动授权 | **测"拒绝权限"场景时要关掉** |
| `unicodeKeyboard`/`resetKeyboard` | 中文输入 | 中文输入常见问题 |
| `newCommandTimeout` | 命令超时 | 默认 60s，长操作会断 |

---

## 2. 元素定位：用 Inspector 看，用 id 定位

### 2.1 定位方式优先级

| 优先 | Android | iOS | 说明 |
| --- | --- | --- | --- |
| 1 | `AppiumBy.ID`（= resource-id） | `AppiumBy.ACCESSIBILITY_ID` | 最稳，和 UI 结构解耦 |
| 2 | `AppiumBy.ANDROID_UIAUTOMATOR`（text/content-desc） | `AppiumBy.IOS_PREDICATE` | 灵活，但依赖文案 |
| 3 | `AppiumBy.ACCESSIBILITY_ID`（content-desc） | `AppiumBy.NAME` | 语义化 |
| 4 | XPath | XPath | **最后选择**，慢且脆 |
| ✗ | 坐标点击 | 坐标点击 | 不同分辨率必挂 |

```python
from appium.webdriver.common.appiumby import AppiumBy

# ✅ 稳：resource-id
driver.find_element(AppiumBy.ID, "com.example.app:id/btn_login").click()

# ✅ 稳：accessibility
driver.find_element(AppiumBy.ACCESSIBILITY_ID, "登录按钮").click()

# ⚠️ 中：文案（改文案就挂，但可读性好）
driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,
                    'new UiSelector().text("登录")').click()

# ❌ 脆：XPath 层级
driver.find_element(AppiumBy.XPATH,
                    '//android.widget.FrameLayout[1]/android.widget.LinearLayout[2]/android.widget.Button[1]')
```

### 2.2 怎么拿到这些属性

- **Android**：`uiautomatorviewer`（SDK 自带）或 **Appium Inspector**（`appium inspector` 或桌面版）。
- **iOS**：Appium Inspector + Xcode 的 Accessibility Inspector。
- 快速定位不到时，用 `adb shell uiautomator dump` 导出当前界面 XML，直接看属性。

```bash
adb shell uiautomator dump /sdcard/ui.xml
adb pull /sdcard/ui.xml
```

**推动开发加 `resource-id`** 和推动前端加 `data-testid` 是同一个道理 —— 这是让用例"改版不崩"的唯一投资。

### 2.3 等待：App 比 Web 更需要显式等待

```python
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

wait = WebDriverWait(driver, 15)
wait.until(EC.element_to_be_clickable((AppiumBy.ID, "com.example.app:id/btn_login"))).click()
```

**为什么隐含等待不适合 App**：App 启动慢（冷启动 3~8 秒）、页面切换有转场动画、列表懒加载。隐式等待全局生效且只等"存在"，很容易在"元素存在但不可点"时失败。

---

## 3. 常用操作（真实场景那几个）

```python
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.actions.action_builder import ActionBuilder

# 输入
el = driver.find_element(AppiumBy.ID, "com.example.app:id/et_phone")
el.clear()
el.send_keys("13800000000")
driver.hide_keyboard()                    # 收起键盘（遮挡按钮时必用）

# 滑动（W3C 手势，比弃用的 swipe 更稳）
driver.execute_script("mobile: swipeGesture", {
    "left": 100, "top": 800, "width": 700, "height": 600,
    "direction": "up", "percent": 0.8,
})

# 长按
driver.execute_script("mobile: longClickGesture", {
    "elementId": el.id, "duration": 1500,
})

# 滚动到元素（列表场景）
el = driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,
                         'new UiScrollable(new UiSelector().scrollable(true))'
                         '.scrollIntoView(new UiSelector().text("设置"))')

# 应用状态控制（比重启 driver 快）
driver.terminate_app("com.example.app")
driver.activate_app("com.example.app")
```

---

## 4. 自查 Q7 完整作答：权限弹窗处理 + 弱网模拟

### 4.1 权限弹窗：三种处理策略，按测试目的选

**策略一：预授权（最省事，适合"权限不是被测点"的时候）**

```python
options.set_capability("autoGrantPermissions", True)     # Android
options.set_capability("autoAcceptAlerts", True)          # iOS
```

- 效果：装 App 时就把所有权限授予，运行时不再弹窗。
- **适用**：测业务功能，权限只是干扰项。
- **不适用**：需求里明确要测"用户拒绝权限后 App 怎么降级"。

**策略二：识别并点击系统弹窗（要测拒绝时用）**

Android 的系统权限弹窗不在你的 App 里，在系统包 `com.android.permissioncontroller`（Android 11+）或 `com.android.packageinstaller`（老版本）：

```python
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def handle_permission_popup(driver, allow: bool = True, timeout: int = 5):
    """处理 Android 系统权限弹窗。allow=True 点允许，False 点拒绝。"""
    try:
        btn_id = "com.android.permissioncontroller:id/permission_allow_foreground_only_button" if allow \
            else "com.android.permissioncontroller:id/permission_deny_button"
        btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((AppiumBy.ID, btn_id)))
        btn.click()
        return True
    except Exception:
        return False        # 没有弹窗（已授权或没触发），不算失败


def test_location_permission_denied(driver):
    """拒绝定位权限后，App 应降级为手动选城市，而不是白屏。"""
    driver.find_element(AppiumBy.ID, "com.example.app:id/btn_nearby").click()
    handle_permission_popup(driver, allow=False)

    # 关键：断言"降级后的表现"，不是断言"弹窗出现了"
    assert driver.find_element(AppiumBy.ID, "com.example.app:id/tv_city_hint").text
 
```

**iOS 的弹窗在 SpringBoard 里**：

```python
from appium.webdriver.common.appiumby import AppiumBy

def handle_ios_alert(driver, allow: bool = True):
    """iOS 系统权限弹窗：在 SpringBoard 应用里定位按钮。"""
    springboard = driver.execute_script("mobile: activeAppInfo")  # 或用 XCUITest 直接切
    btn = "允许" if allow else "不允许"
    try:
        driver.find_element(AppiumBy.ACCESSIBILITY_ID, btn).click()
        return True
    except Exception:
        return False
```

**策略三：修改系统设置（要测"关闭权限"的长期状态时）**

```bash
# Android：用 adb 直接改权限（需要 root 或 debug 包）
adb shell pm revoke com.example.app android.permission.ACCESS_FINE_LOCATION
adb shell pm grant  com.example.app android.permission.ACCESS_FINE_LOCATION
```

**三种策略的选择（答题要点）**：

| 测试目的 | 用哪种 |
| --- | --- |
| 测业务，权限是干扰 | 预授权（`autoGrantPermissions`） |
| 测"拒绝权限后的降级" | 识别系统弹窗并点拒绝 |
| 测"权限被关闭后长期表现" | adb pm revoke/grant |
| 测"权限只授予一次" | 先授予，再重启 App 看是否再弹 |

**三个必踩的坑**：

1. **不要用坐标点击弹窗** —— 不同分辨率、不同系统版本按钮位置不同，必挂。
2. **弹窗出现有延迟** —— 点完按钮后弹窗可能 1~2 秒才出现，用 `WebDriverWait` 等，不要立即断言。
3. **Android 11+ 的按钮 id 变了** —— 老的 `packageinstaller:id/permission_allow_button` 在新系统上找不到，要按系统版本分支。

### 4.2 弱网模拟：Appium 不管这事，要用外部手段

**Appium 本身没有弱网能力**，必须靠设备/系统/代理层。四种方案：

| 方案 | 适用 | 怎么做 |
| --- | --- | --- |
| **Android 模拟器自带参数** | 模拟器上跑 | 启动时加 `-netdelay 2000 -netspeed gsm`，或运行时 `adb emu network delay 2000` |
| **iOS Network Link Conditioner** | 真机/模拟器 | Xcode 的 Additional Tools 里安装，选预设（3G/Edge/100% Loss） |
| **用 PC 开热点 + tc netem** | Android 真机 | PC 做热点，Linux 上用 `tc qdisc add dev wlan0 root netem delay 2000ms loss 5%` |
| **代理工具限速** | 通用（HTTP 层） | Charles/Reqable 的 Throttle 预设，或 mitmproxy 插件加延迟 |

**最实用的两个**：

```bash
# 1. Android 模拟器（改完立刻生效，不用重启）
adb emu network delay 3000          # 延迟 3s
adb emu network speed gsm           # 限速到 GSM 级别
adb emu network delay none          # 恢复

# 2. mitmproxy 插件做 HTTP 层限速（真机也能用）
# throttle.py
import time
from mitmproxy import http

def response(flow: http.HTTPFlow) -> None:
    time.sleep(3.0)                 # 每个响应都延迟 3 秒
```

```bash
mitmdump -s throttle.py
```

**弱网要测什么**（这一步比"怎么模拟"更重要）：

| 弱网场景 | 期望 |
| --- | --- |
| 首屏加载慢 | 有 loading / 骨架屏，不白屏 |
| 提交订单超时 | 提示"网络超时，请重试"，**不能出现"订单失败但实际成功"** |
| 弱网下重复点击 | 按钮置灰/只发一次请求（查后端是否产生两单） |
| 断网 | 明确提示"网络不可用"，恢复后能自动重试 |
| 切换网络（WiFi↔4G） | 长连接是否重连、请求是否丢失 |

---

## 5. 日志与崩溃：失败时最先看的两样

### 5.1 adb logcat

```bash
# 按进程过滤（最常用）
adb logcat --pid=$(adb shell pidof com.example.app)

# 按 tag / 级别过滤
adb logcat -s "MyApp:D" "AndroidRuntime:E"

# 清空后重新抓（复现前先清，日志才干净）
adb logcat -c && adb logcat > run.log

# 抓崩溃栈
adb logcat -b crash
```

### 5.2 Appium 里拿 logcat

```python
logs = driver.get_log("logcat")         # Android 支持
errors = [l for l in logs if l["levelname"] in ("ERROR", "SEVERE")]
```

### 5.3 崩溃后怎么办

| 现象 | 先看 | 结论 |
| --- | --- | --- |
| App 直接闪退 | `adb logcat -b crash` | 找 `FATAL EXCEPTION` + 堆栈 → 提缺陷（带堆栈） |
| App 卡在启动页 | logcat + 是否 ANR | ANR 看 `traces.txt`（`/data/anr/`） |
| 元素找不到但界面看得到 | `uiautomator dump` 看控件树 | 可能是 WebView/Flutter/自定义 View（控件树里没有） |
| 偶发失败但无崩溃 | 截图 + 录屏 | 多半是等待问题 |
| 设备断开 | `adb devices` | 模拟器挂了/USB 松了，与业务无关 |

**一个必知的事实**：Flutter、React Native、游戏引擎的界面，**原生控件树里可能只有一个 SurfaceView，元素全查不到**。遇到这种情况要么用 Flutter 的测试 API，要么只能截图 + 坐标（脆弱），要么推动开发加语义标注。**这是"选型时就要评估"的事**。

---

## 6. 多机型兼容与云真机

| 方式 | 优点 | 缺点 |
| --- | --- | --- |
| 本地几台真机 | 便宜、可控 | 覆盖少、维护烦 |
| 本地模拟器 | 快、可批量 | 测不出真实性能/厂商 ROM 差异 |
| **云真机平台**（Testin/WeTest/BrowserStack/Sauce Labs/阿里云 EMAS） | 机型多、支持并行、有录屏日志 | 收费、网络延迟、调试不如本地顺手 |

**兼容性测试的组合策略**（配合《用例设计方法篇》的正交法）：

```
必测：主流机型 3~5 台（覆盖高中低端 + 主流系统版本）
抽样：厂商 ROM（小米/华为/OPPO 各 1）—— 权限、后台保活、推送差异都在这里
专项：屏幕比例（刘海屏/折叠屏）、系统版本边界（最低支持版本）
```

---

## 7. App 自动化的五个"只有做过才知道"的坑

| 坑 | 现象 | 解法 |
| --- | --- | --- |
| **启动广告/升级弹窗** | 每次启动都弹，用例第一步就挂 | 启动后统一处理一次（`handle_startup_popups`），或用测试包关掉 |
| **Toast 抓不到** | Android Toast 不在控件树里 | 用 `uiautomator2` 的 toast 捕获（Appium 需特定能力），或截图后 OCR（下策） |
| **Hybrid 应用（WebView）** | 控件树里看到 `android.webkit.WebView`，里面元素找不到 | `driver.switch_to.context(driver.contexts[-1])` 切到 WebView 上下文 |
| **冷启动 vs 热启动** | 冷启动慢 5 秒，热启动快 | 用例不假设启动耗时；首屏断言用显式等待 |
| **被系统杀后台** | 切到其他 App 再回来，页面重置 | 不只测前台流程，也要测"后台切回" |

```python
def handle_startup_popups(driver):
    """启动后统一关掉广告/升级/评分弹窗。找不到就跳过，不失败。"""
    for _ in range(3):
        closed = False
        for locator in [
            (AppiumBy.ID, "com.example.app:id/iv_close_ad"),
            (AppiumBy.ID, "com.example.app:id/btn_later"),
            (AppiumBy.XPATH, '//*[@text="以后再说"]'),
        ]:
            try:
                driver.find_element(*locator).click()
                closed = True
                break
            except Exception:
                continue
        if not closed:
            break
```

---

## 8. 动手清单

- [ ] 用 `appium inspector` 连接一次真机，把一个页面的所有可定位元素导出看一遍。
- [ ] 写一个 `handle_startup_popups`，看能不能把启动弹窗全部关掉。
- [ ] 用 `adb emu network delay 3000` 造一次弱网，看下单流程的表现。
- [ ] 抓一次 `adb logcat -b crash`，体会崩溃栈怎么定位到代码行。
- [ ] 数一下你的脚本里有多少 `find_element(By.XPATH, ...)`，逐个换成 resource-id。
