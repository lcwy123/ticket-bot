/**
 * AutoJS 服务端脚本
 * 运行在手机上，接收服务器指令并执行自动化操作
 *
 * 使用方式：
 * 1. 安装 AutoJS
 * 2. 开启辅助功能权限
 * 3. 运行此脚本
 * 4. 脚本会在手机本地启动 HTTP 服务，监听指令
 */

let TAG = "XianyuAgent";

// ========== 配置 ==========
let CONFIG = {
    port: 8888,           // HTTP 服务端口
    serverUrl: "http://localhost:8888",  // 本地服务地址
    autoStart: true,       // 自动开始服务
    debugMode: true
};

// ========== 全局状态 ==========
let isRunning = false;
let serverSocket = null;
let accessibilityService = null;

// ========== 日志 ==========
function log(msg) {
    if (CONFIG.debugMode) {
        console.log("[" + TAG + "] " + msg);
        toast("[" + TAG + "] " + msg);
    }
}

function logError(msg) {
    console.error("[" + TAG + "] ERROR: " + msg);
    toast("[" + TAG + "] ERROR: " + msg);
}

// ========== 辅助功能服务 ==========
let MyAccessibilityService = {
    service: null,

    init: function() {
        try {
            // 尝试获取辅助功能服务
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
        if (!this.service) {
            return { success: false, error: "服务未连接" };
        }
        try {
            let result = this.service.click(x, y);
            return { success: result, action: "click", x: x, y: y };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    // 执行滑动
    swipe: function(x1, y1, x2, y2, duration) {
        if (!this.service) {
            return { success: false, error: "服务未连接" };
        }
        try {
            duration = duration || 500;
            let result = this.service.swipe(x1, y1, x2, y2, duration);
            return { success: result, action: "swipe", from: [x1, y1], to: [x2, y2], duration: duration };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    // 输入文本
    inputText: function(text) {
        if (!this.service) {
            return { success: false, error: "服务未连接" };
        }
        try {
            // 设置剪贴板内容
            setClip(text);
            // 模拟粘贴操作
            this.service.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_PASTE);
            return { success: true, action: "input", text: text };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    // 按返回键
    pressBack: function() {
        if (!this.service) {
            return { success: false, error: "服务未连接" };
        }
        try {
            this.service.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_BACK);
            return { success: true, action: "back" };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    // 按 Home 键
    pressHome: function() {
        if (!this.service) {
            return { success: false, error: "服务未连接" };
        }
        try {
            this.service.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_HOME);
            return { success: true, action: "home" };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    },

    // 获取当前界面文本
    getText: function() {
        if (!this.service) {
            return "";
        }
        try {
            let root = this.service.getRootInActiveWindow();
            if (root) {
                return root.getText() || "";
            }
        } catch (e) {
            logError("获取文本失败: " + e);
        }
        return "";
    },

    // 查找元素并点击
    findAndClick: function(text) {
        if (!this.service) {
            return { success: false, error: "服务未连接" };
        }
        try {
            let root = this.service.getRootInActiveWindow();
            if (!root) {
                return { success: false, error: "无法获取界面" };
            }

            let nodes = root.findAll(android.view.accessibility.AccessibilityNodeInfo);
            for (let i = 0; i < nodes.size(); i++) {
                let node = nodes.get(i);
                let nodeText = node.getText();
                if (nodeText && nodeText.toString().indexOf(text) != -1) {
                    let bounds = new android.graphics.Rect();
                    node.getBoundsInScreen(bounds);
                    let cx = bounds.centerX();
                    let cy = bounds.centerY();
                    let result = this.service.click(cx, cy);
                    node.recycle();
                    return { success: result, action: "findAndClick", text: text, x: cx, y: cy };
                }
                node.recycle();
            }
            return { success: false, error: "未找到元素: " + text };
        } catch (e) {
            return { success: false, error: "" + e };
        }
    }
};

// ========== HTTP 服务器 ==========
function startServer() {
    if (isRunning) {
        log("服务已在运行");
        return;
    }

    // 检查辅助功能权限
    if (!MyAccessibilityService.isEnabled()) {
        logError("请先开启辅助功能权限");
        dialogs.confirm({
            title: "需要权限",
            content: "此脚本需要辅助功能权限才能正常工作。\n\n请在设置 → 无障碍 → 已下载的APP → AutoJS → 开启此权限。",
            positiveText: "去设置",
            negativeText: "取消",
            callback: function() {
                app.startActivity("accessibility");
            }
        });
        return;
    }

    MyAccessibilityService.init();

    try {
        // 使用 okhttp 插件创建 HTTP 服务器
        let server = servers.createHttpServer(CONFIG.port);

        server.on("request", function(request, response) {
            handleRequest(request, response);
        });

        server.on("error", function(e) {
            logError("服务器错误: " + e);
        });

        serverSocket = server;
        isRunning = true;
        log("HTTP 服务已启动，端口: " + CONFIG.port);
        log("等待指令...");

    } catch (e) {
        logError("启动服务器失败: " + e);
        // 尝试使用原生 HTTP 服务器
        startNativeServer();
    }
}

function startNativeServer() {
    try {
        // 使用 threads 创建简单的 HTTP 监听
        log("尝试启动原生服务器...");
        // AutoJS 的原生方式需要插件支持，这里用 setInterval 模拟
    } catch (e) {
        logError("原生服务器也失败: " + e);
    }
}

function handleRequest(request, response) {
    let method = request.method;
    let path = request.path;
    let body = request.body || {};

    log("收到请求: " + method + " " + path);

    // 设置 CORS 头
    response.setHeader("Access-Control-Allow-Origin", "*");
    response.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    response.setHeader("Access-Control-Allow-Headers", "Content-Type");

    if (method == "OPTIONS") {
        response.status = 200;
        response.send("");
        return;
    }

    let result = null;
    let action = "";

    try {
        // 解析请求体
        let data = null;
        if (body) {
            try {
                data = typeof(body) == "string" ? JSON.parse(body) : body;
            } catch (e) {
                data = {};
            }
        }

        // 处理不同指令
        action = data.action || path.replace("/", "");

        switch (action) {
            case "click":
            case "tap":
                result = MyAccessibilityService.click(data.x || 0, data.y || 0);
                break;

            case "swipe":
                result = MyAccessibilityService.swipe(
                    data.x1 || 0, data.y1 || 0,
                    data.x2 || 0, data.y2 || 0,
                    data.duration || 500
                );
                break;

            case "input":
            case "text":
                result = MyAccessibilityService.inputText(data.text || "");
                break;

            case "back":
                result = MyAccessibilityService.pressBack();
                break;

            case "home":
                result = MyAccessibilityService.pressHome();
                break;

            case "find":
                result = MyAccessibilityService.findAndClick(data.text || "");
                break;

            case "screenshot":
                result = takeScreenshot();
                break;

            case "getText":
                result = { success: true, text: MyAccessibilityService.getText() };
                break;

            case "status":
                result = {
                    success: true,
                    running: isRunning,
                    accessibilityEnabled: MyAccessibilityService.isEnabled(),
                    action: "status"
                };
                break;

            case "ping":
                result = { success: true, action: "pong", timestamp: Date.now() };
                break;

            default:
                result = { success: false, error: "未知指令: " + action };
        }

    } catch (e) {
        logError("处理请求失败: " + e);
        result = { success: false, error: "" + e };
    }

    // 发送响应
    try {
        response.status = 200;
        response.send(JSON.stringify(result));
        log("响应: " + JSON.stringify(result));
    } catch (e) {
        logError("发送响应失败: " + e);
    }
}

function takeScreenshot() {
    try {
        let img = captureScreen();
        if (img) {
            // 保存到文件
            let path = "/sdcard/autojs_screenshot_" + Date.now() + ".png";
            img.saveTo(path);
            return { success: true, path: path, action: "screenshot" };
        }
        return { success: false, error: "截图失败" };
    } catch (e) {
        return { success: false, error: "" + e };
    }
}

function stopServer() {
    if (serverSocket) {
        try {
            serverSocket.close();
        } catch (e) {
            logError("关闭服务器失败: " + e);
        }
        serverSocket = null;
    }
    isRunning = false;
    log("服务已停止");
}

// ========== 主程序 ==========
function main() {
    log("=".repeat(50));
    log("闲鱼 Agent AutoJS 服务");
    log("=" .repeat(50));
    log("配置: 端口 " + CONFIG.port);
    log("=" .repeat(50));

    if (CONFIG.autoStart) {
        startServer();
    }

    // 监听退出事件
    events.on("exit", function() {
        log("脚本即将退出，停止服务...");
        stopServer();
    });
}

// 运行主程序
main();

// ========== 对外接口（用于 AutoJS 控制台） ==========
module.exports = {
    start: startServer,
    stop: stopServer,
    status: function() {
        return {
            running: isRunning,
            accessibilityEnabled: MyAccessibilityService.isEnabled()
        };
    }
};
