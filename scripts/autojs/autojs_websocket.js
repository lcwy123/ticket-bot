/**
 * AutoJS6 WebSocket 客户端脚本
 * 使用官方 WebSocket API 与服务器通信
 */

let TAG = "XianyuAgent";

// ========== 配置 ==========
let CONFIG = {
    wsUrl: "ws://121.43.146.124:8000/api/agent/device/ws/my_phone",
    debugMode: true
};

// ========== 全局状态 ==========
let ws = null;
let isConnected = false;
let reconnectTimer = null;

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

    click: function(x, y) {
        try {
            let result = click(x, y);
            log("执行点击: (" + x + ", " + y + ") -> " + result);
            return { success: result, action: "click", x: x, y: y };
        } catch (e) {
            log("点击异常: " + e);
            return { success: false, error: "" + e };
        }
    },

    swipe: function(x1, y1, x2, y2, duration) {
        try {
            let dur = duration || 500;
            let result = swipe(x1, y1, x2, y2, dur);
            log("执行滑动: (" + x1 + "," + y1 + ") -> (" + x2 + "," + y2 + ") -> " + result);
            return { success: result, action: "swipe" };
        } catch (e) {
            log("滑动异常: " + e);
            return { success: false, error: "" + e };
        }
    },

    inputText: function(text) {
        try {
            setClip(text);
            sleep(100);
            if (this.service) {
                this.service.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_PASTE);
            }
            return { success: true, action: "input", text: text };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    pressBack: function() {
        try {
            if (this.service) {
                this.service.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_BACK);
            }
            return { success: true, action: "back" };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    pressHome: function() {
        try {
            if (this.service) {
                this.service.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_HOME);
            }
            return { success: true, action: "home" };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    _captureGranted: false,

    requestCapturePermission: function() {
        if (this._captureGranted) return true;
        log("请求截图权限...");
        let granted = requestScreenCapture();
        log("截图权限申请结果: " + granted);
        this._captureGranted = granted;
        if (!granted) {
            toast("截图权限申请失败，请手动授权");
        }
        return granted;
    },

    takeScreenshot: function() {
        try {
            // 先请求截图权限
            if (!this._captureGranted) {
                this.requestCapturePermission();
            }
            if (!this._captureGranted) {
                return { success: false, error: "截图权限未授权" };
            }
            // 等待一下让权限生效
            sleep(500);
            let img = captureScreen();
            if (img) {
                let path = "/sdcard/autojs_screenshot.png";
                images.save(img, path, "png", 100);
                img.recycle();
                log("截图已保存: " + path);
                return { success: true, path: path };
            }
            return { success: false, error: "截图失败" };
        } catch (e) {
            logError("截图异常: " + e);
            return { success: false, error: "" + e };
        }
    },

    getText: function() {
        try {
            if (this.service) {
                let root = this.service.getRootInActiveWindow();
                if (root) {
                    let text = root.getText();
                    root.recycle();
                    return { success: true, text: text || "" };
                }
            }
            return { success: false, error: "无法获取界面" };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    findAndClick: function(text) {
        try {
            if (!this.service) {
                // 尝试用全局 click
                let result = click(0, 0);
                return { success: false, error: "服务未连接" };
            }
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
    },

    launchApp: function(appName) {
        try {
            launchApp(appName);
            return { success: true, action: "launch", app: appName };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    }
};

// ========== WebSocket 连接 ==========
function connect() {
    if (isConnected) {
        log("已经在连接中");
        return;
    }

    AccessibilityClient.init();

    log("准备连接: " + CONFIG.wsUrl);

    try {
        ws = new WebSocket(CONFIG.wsUrl);
        ws.exitOnClose();

        ws.on(WebSocket.EVENT_OPEN, function(res, ws) {
            log("WebSocket 已连接！");
            isConnected = true;
            toast("已连接到服务器");

            let msg = JSON.stringify({
                type: "register",
                device_id: "my_phone",
                device_name: android.os.Build.MODEL
            });
            ws.send(msg);
            log("注册消息已发送: " + msg);
        });

        ws.on(WebSocket.EVENT_TEXT, function(text, ws) {
            log("收到文本消息: " + text);
            try {
                let data = JSON.parse(text);
                handleMessage(data);
            } catch (e) {
                logError("解析消息失败: " + e);
            }
        });

        ws.on(WebSocket.EVENT_BYTES, function(bytes, ws) {
            log("收到字节消息: " + bytes.utf8());
        });

        ws.on(WebSocket.EVENT_CLOSING, function(code, reason, ws) {
            log("WebSocket 关闭中... code: " + code + ", reason: " + reason);
        });

        ws.on(WebSocket.EVENT_CLOSED, function(code, reason, ws) {
            log("WebSocket 已关闭. code: " + code + ", reason: " + reason);
            isConnected = false;
            ws = null;
            scheduleReconnect();
        });

        ws.on(WebSocket.EVENT_FAILURE, function(err, res, ws) {
            logError("WebSocket 连接失败: " + JSON.stringify(err));
            isConnected = false;
            ws = null;
            scheduleReconnect();
        });

        log("WebSocket 对象已创建，等待服务器响应...");

    } catch (e) {
        logError("创建 WebSocket 失败: " + e);
        scheduleReconnect();
    }
}

function disconnect() {
    isConnected = false;
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }
    if (ws) {
        try {
            ws.close(WebSocket.CODE_CLOSE_NORMAL, "用户断开连接");
        } catch (e) {
            logError("关闭连接失败: " + e);
        }
        ws = null;
    }
    log("已断开连接");
}

function scheduleReconnect() {
    if (reconnectTimer) return;
    log("5秒后尝试重连...");
    reconnectTimer = setTimeout(function() {
        reconnectTimer = null;
        connect();
    }, 5000);
}

// ========== 消息处理 ==========
function handleMessage(data) {
    log("处理消息: " + JSON.stringify(data));

    if (data.type == "command") {
        executeCommand(data);
    } else if (data.type == "ping") {
        if (ws) {
            ws.send(JSON.stringify({ type: "pong", timestamp: Date.now() }));
        }
    } else if (data.type == "connected") {
        log("收到服务器连接确认: " + JSON.stringify(data));
        toast("服务器连接成功");
    }
}

function executeCommand(cmd) {
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
                toast("输入: " + cmd.text);
                result = AccessibilityClient.inputText(cmd.text || "");
                break;

            case "back":
                toast("返回");
                result = AccessibilityClient.pressBack();
                break;

            case "home":
                toast("Home");
                result = AccessibilityClient.pressHome();
                break;

            case "screenshot":
                toast("截图");
                result = AccessibilityClient.takeScreenshot();
                break;

            case "requestCapture":
                toast("申请截图权限...");
                let granted = AccessibilityClient.requestCapturePermission();
                result = { success: granted, message: granted ? "权限申请成功" : "权限申请失败，请在AutoJS中运行脚本" };
                break;

            case "getText":
                result = AccessibilityClient.getText();
                break;

            case "find":
                toast("查找: " + cmd.text);
                result = AccessibilityClient.findAndClick(cmd.text || "");
                break;

            case "launch":
                toast("启动: " + cmd.app);
                result = AccessibilityClient.launchApp(cmd.app || "");
                break;

            default:
                result = { success: false, error: "未知指令: " + cmd.action };
        }
    } catch (e) {
        result = { success: false, error: "" + e };
    }

    if (ws && isConnected) {
        try {
            let response = JSON.stringify({
                type: "result",
                command_id: cmd.id,
                result: result,
                timestamp: Date.now()
            });
            ws.send(response);
            log("结果已发送: " + JSON.stringify(result));
        } catch (e) {
            logError("发送结果失败: " + e);
        }
    }
}

// ========== 启动 ==========
function main() {
    log("=".repeat(50));
    log("闲鱼 Agent WebSocket 客户端 (AutoJS6)");
    log("服务器: " + CONFIG.wsUrl);
    log("=".repeat(50));

    toast("正在连接服务器...");
    connect();

    toast("脚本已启动，等待服务器指令...");

    threads.start(function() {
        log("守护线程启动");
        while (true) {
            sleep(1000);
            if (!isConnected && !reconnectTimer) {
                log("检测到断开，尝试重连...");
                scheduleReconnect();
            }
        }
    });

    log("脚本已就绪，保持运行...");
}

main();
