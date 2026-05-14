/**
 * AutoJS 轮询客户端脚本
 * 运行在手机上，定期从服务器获取指令并执行
 *
 * 使用方式：
 * 1. 安装 AutoJS
 * 2. 开启辅助功能权限
 * 3. 修改下方 CONFIG 配置
 * 4. 运行此脚本
 */

let TAG = "XianyuAgent";

// ========== 配置 ==========
let CONFIG = {
    // 服务器地址
    baseUrl: "http://121.43.146.124:8000/api/agent/device",
    deviceId: "my_phone",
    pollInterval: 1000,      // 轮询间隔（毫秒）
    debugMode: true
};

// ========== 全局状态 ==========
let isRunning = false;
let lastCommandId = null;
let pendingCommand = null;  // 待执行的命令

// ========== 日志 ==========
function log(msg) {
    if (CONFIG.debugMode) {
        console.log("[" + TAG + "] " + msg);
    }
}

function logError(msg) {
    console.error("[" + TAG + "] ERROR: " + msg);
    toast("[" + TAG + "] ERROR: " + msg);
}

// ========== 辅助功能服务 ==========
let AccessibilityClient = {
    service: null,

    init: function() {
        try {
            let service = auto.service;
            if (service) {
                this.service = service;
                log("辅助功能服务已连接");
                return true;
            }
        } catch (e) {
            logError("获取辅助功能服务失败: " + e);
        }
        return false;
    },

    isEnabled: function() {
        try {
            return auto.service != null;
        } catch (e) {
            return false;
        }
    },

    // 执行点击
    click: function(x, y) {
        if (!this.service) return { success: false, error: "服务未连接" };
        try {
            let result = this.service.click(x, y);
            return { success: result !== false, action: "click", x: x, y: y };
        } catch (e) {
            // 如果 direct click 失败，尝试用 shell input tap
            try {
                shell("input tap " + x + " " + y, true);
                return { success: true, action: "click", x: x, y: y };
            } catch (e2) {
                return { success: false, error: "" + e2 };
            }
        }
    },

    // 执行滑动
    swipe: function(x1, y1, x2, y2, duration) {
        if (!this.service) return { success: false, error: "服务未连接" };
        try {
            let result = this.service.swipe(x1, y1, x2, y2, duration || 500);
            return { success: result !== false, action: "swipe" };
        } catch (e) {
            // 备选：用 shell swipe
            try {
                shell("input swipe " + x1 + " " + y1 + " " + x2 + " " + y2, false);
                return { success: true, action: "swipe" };
            } catch (e2) {
                return { success: false, error: "" + e2 };
            }
        }
    },

    // 输入文本（通过剪贴板方式）
    inputText: function(text) {
        if (!this.service) return { success: false, error: "服务未连接" };
        try {
            setClip(text);
            sleep(100);
            this.service.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_PASTE);
            return { success: true, action: "input", text: text };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    // 按返回键
    pressBack: function() {
        if (!this.service) return { success: false, error: "服务未连接" };
        try {
            this.service.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_BACK);
            return { success: true, action: "back" };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    // 按 Home 键
    pressHome: function() {
        if (!this.service) return { success: false, error: "服务未连接" };
        try {
            this.service.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_HOME);
            return { success: true, action: "home" };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    // 截图
    takeScreenshot: function() {
        try {
            let img = captureScreen();
            if (img) {
                let path = "/sdcard/autojs_screenshot_" + Date.now() + ".png";
                img.saveTo(path);
                return { success: true, path: path };
            }
            return { success: false, error: "截图失败" };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    // 获取当前界面文本
    getText: function() {
        if (!this.service) return "";
        try {
            let root = this.service.getRootInActiveWindow();
            if (root) {
                let text = root.getText();
                root.recycle();
                return text || "";
            }
        } catch (e) {
            logError("获取文本失败: " + e);
        }
        return "";
    },

    // 查找并点击元素
    findAndClick: function(text) {
        if (!this.service) return { success: false, error: "服务未连接" };
        try {
            let root = this.service.getRootInActiveWindow();
            if (!root) return { success: false, error: "无法获取界面" };

            let nodes = root.findAll(android.view.accessibility.AccessibilityNodeInfo);
            for (let i = 0; i < nodes.size(); i++) {
                let node = nodes.get(i);
                let nodeText = node.getText();
                if (nodeText && nodeText.toString().indexOf(text) != -1) {
                    let bounds = new android.graphics.Rect();
                    node.getBoundsInScreen(bounds);
                    let cx = bounds.centerX();
                    let cy = bounds.centerY();
                    node.recycle();
                    root.recycle();
                    return this.click(cx, cy);
                }
                node.recycle();
            }
            root.recycle();
            return { success: false, error: "未找到: " + text };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    }
};

// ========== 命令队列（解决主线程问题）==========
let commandQueue = null;
let resultQueue = null;

// ========== HTTP 客户端（后台线程）=========
let httpThread = null;
let httpRunning = false;

function startHttpThread() {
    if (httpRunning) return;
    httpRunning = true;

    httpThread = threads.start(function() {
        log("HTTP 线程已启动（自动注册）");

        while (httpRunning) {
            try {
                // 获取命令（服务器会自动注册设备）
                let url = CONFIG.baseUrl + "/command?device_id=" + CONFIG.deviceId + "&last_id=" + (lastCommandId || "");
                let response = http.get(url, {
                    timeout: 5000
                });

                if (response.statusCode == 200) {
                    let data = JSON.parse(response.body.string());
                    if (data.has_command && data.command && data.command.id != lastCommandId) {
                        log("收到命令: " + data.command.action);
                        lastCommandId = data.command.id;
                        pendingCommand = data.command;
                    }
                }
            } catch (e) {
                // 忽略网络错误，继续轮询
            }

            // 上报待处理的结果
            if (resultQueue && resultQueue.length > 0) {
                let item = resultQueue.shift();
                try {
                    let reportUrl = CONFIG.baseUrl + "/result?device_id=" + CONFIG.deviceId;
                    let body = JSON.stringify({
                        command_id: item.commandId,
                        result: item.result,
                        timestamp: Date.now()
                    });
                    http.post(reportUrl, body, {
                        headers: { "Content-Type": "application/json" },
                        timeout: 5000
                    });
                    log("结果已上报: " + item.commandId);
                } catch (e) {
                    // 失败则放回队列
                    resultQueue.unshift(item);
                }
            }

            sleep(CONFIG.pollInterval);
        }
        log("HTTP 线程已停止");
    });
}

function stopHttpThread() {
    httpRunning = false;
    if (httpThread) {
        httpThread.interrupt();
        httpThread = null;
    }
}

// ========== 命令执行 ==========
function executePendingCommand() {
    if (!pendingCommand) return;

    let cmd = pendingCommand;
    pendingCommand = null;  // 清空，等待处理
    log("执行指令: " + cmd.action);
    toast("执行命令: " + cmd.action);

    let result = null;

    try {
        switch (cmd.action) {
            case "click":
            case "tap":
                toast("点击: (" + cmd.x + ", " + cmd.y + ")");
                result = AccessibilityClient.click(cmd.x || 0, cmd.y || 0);
                break;

            case "swipe":
                toast("滑动: (" + cmd.x1 + "," + cmd.y1 + ") -> (" + cmd.x2 + "," + cmd.y2 + ")");
                result = AccessibilityClient.swipe(
                    cmd.x1 || 0, cmd.y1 || 0,
                    cmd.x2 || 0, cmd.y2 || 0,
                    cmd.duration || 500
                );
                break;

            case "input":
            case "text":
                toast("输入文本: " + cmd.text);
                result = AccessibilityClient.inputText(cmd.text || "");
                break;

            case "back":
                toast("按返回键");
                result = AccessibilityClient.pressBack();
                break;

            case "home":
                toast("按 Home 键");
                result = AccessibilityClient.pressHome();
                break;

            case "screenshot":
                toast("截图中...");
                result = AccessibilityClient.takeScreenshot();
                break;

            case "getText":
                result = { success: true, text: AccessibilityClient.getText() };
                break;

            case "find":
                toast("查找: " + cmd.text);
                result = AccessibilityClient.findAndClick(cmd.text || "");
                break;

            case "launch":
                toast("启动: " + cmd.app);
                try {
                    // 尝试直接启动
                    let launched = false;
                    try {
                        launched = launchApp(cmd.app);
                    } catch (e) {}
                    if (!launched) {
                        // 尝试用 shell 启动
                        try {
                            shell("am start -n " + cmd.app, false);
                            launched = true;
                        } catch (e2) {}
                    }
                    result = { success: launched, action: "launch", app: cmd.app };
                } catch (e) {
                    result = { success: false, error: "" + e };
                }
                break;

            default:
                result = { success: false, error: "未知指令: " + cmd.action };
        }
    } catch (e) {
        result = { success: false, error: "" + e };
    }

    // 将结果放入上报队列
    if (!resultQueue) resultQueue = [];
    resultQueue.push({
        commandId: cmd.id,
        result: result
    });

    log("执行完成: " + JSON.stringify(result));
}

// ========== 主循环 ==========
let mainLoop = null;

function startPolling() {
    if (isRunning) {
        log("已经在运行中");
        return;
    }

    // 检查权限
    if (!AccessibilityClient.isEnabled()) {
        logError("请先开启辅助功能权限");
        dialogs.confirm({
            title: "需要权限",
            content: "此脚本需要辅助功能权限。\n\n设置 → 无障碍 → AutoJS → 开启",
            positiveText: "确定"
        });
        return;
    }

    AccessibilityClient.init();

    // 启动 HTTP 线程
    startHttpThread();

    isRunning = true;
    log("开始轮询...");

    // 主循环定时检查待执行命令
    mainLoop = setInterval(function() {
        if (!isRunning) return;

        // 执行待处理的命令
        if (pendingCommand) {
            executePendingCommand();
        }
    }, 200);  // 每 200ms 检查一次

    toast("轮询已启动");
    log("轮询已启动，间隔 " + CONFIG.pollInterval + "ms");
}

function stopPolling() {
    if (mainLoop) {
        clearInterval(mainLoop);
        mainLoop = null;
    }
    stopHttpThread();
    isRunning = false;
    log("轮询已停止");
}

// ========== 启动 ==========
function main() {
    log("=".repeat(50));
    log("闲鱼 Agent AutoJS 客户端");
    log("服务器: " + CONFIG.baseUrl);
    log("设备ID: " + CONFIG.deviceId);
    log("=".repeat(50));

    // 显示操作菜单
    let choice = dialogs.select("选择操作", [
        "1. 开始轮询",
        "2. 停止轮询",
        "3. 测试截图",
        "4. 测试 getText",
        "5. 退出"
    ]);

    switch (choice) {
        case 0:
            startPolling();
            break;
        case 1:
            stopPolling();
            break;
        case 2:
            let r = AccessibilityClient.takeScreenshot();
            toast("截图: " + JSON.stringify(r));
            break;
        case 3:
            toast("界面文本: " + AccessibilityClient.getText());
            break;
        case 4:
        default:
            stopPolling();
            exit();
            break;
    }
}

main();
