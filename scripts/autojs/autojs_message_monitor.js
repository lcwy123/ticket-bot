/**
 * AutoJS 闲鱼消息监控脚本
 * 运行在手机上，监控闲鱼新消息并转发到服务器客服处理
 *
 * 使用方式：
 * 1. 安装 AutoJS
 * 2. 开启辅助功能权限
 * 3. 修改下方 CONFIG 配置
 * 4. 运行此脚本
 */

let TAG = "XianyuMonitor";

// ========== 配置 ==========
let CONFIG = {
    // 服务器地址（客服API）
    serverUrl: "http://121.43.146.124:8000",
    deviceId: "my_phone",
    pollInterval: 2000,        // 消息检查间隔（毫秒）
    debugMode: true
};

// ========== 全局状态 ==========
let isRunning = false;
let lastMessages = {};         // 上次检查时的消息，{conversation: lastContent}
let processedCount = 0;       // 已处理消息计数

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

// ========== 闲鱼包名 ==========
const XIANYU_PACKAGE = "com.taobao.idlefish";

// ========== 检测当前APP ==========
function isXianyuActive() {
    try {
        let current = context.getPackageManager().getLaunchIntentForPackage(XIANYU_PACKAGE);
        let foreground = current != null && activity.getPackageName() == XIANYU_PACKAGE;
        return foreground;
    } catch (e) {
        return false;
    }
}

// ========== 获取闲鱼会话列表 ==========
function getConversations() {
    let result = [];
    try {
        // 尝试使用UiSelector查找会话项
        let selector = text => {
            try {
                return className("android.widget.TextView").text(text).findOnce();
            } catch (e) { return null; }
        };

        // 获取当前界面所有文本
        let root = auto.service.getRootInActiveWindow();
        if (!root) {
            log("无法获取界面");
            return result;
        }

        // 遍历子节点查找会话
        let nodes = root.findAll(className("android.widget.LinearLayout"));
        for (let i = 0; i < nodes.size(); i++) {
            let node = nodes.get(i);
            try {
                let bounds = new android.graphics.Rect();
                node.getBoundsInScreen(bounds);

                // 只处理屏幕右侧区域（消息内容区）
                let screenWidth = context.getResources().getDisplayMetrics().widthPixels;
                if (bounds.left < screenWidth * 0.3) continue;

                let text = node.getText();
                if (text && text.length() > 0 && text.length() < 200) {
                    // 过滤掉明显不是消息的内容
                    let content = text.toString().trim();
                    if (content.length > 1 && !content.includes("http") && content.length < 500) {
                        result.push({
                            text: content,
                            bounds: bounds
                        });
                    }
                }
            } catch (e) {}
            node.recycle();
        }
        root.recycle();
    } catch (e) {
        logError("获取会话失败: " + e);
    }
    return result;
}

// ========== 获取最新消息（从通知栏或聊天界面）==========
function checkNewMessages() {
    let newMessages = [];

    try {
        // 方法1：检查通知栏
        let notifications = getNotifications();
        for (let notif of notifications) {
            if (notif.packageName == XIANYU_PACKAGE || notif.title.includes("闲鱼") || notif.title.includes("鱼")) {
                let key = "notification_" + notif.id;
                if (!lastMessages[key] || lastMessages[key] != notif.content) {
                    newMessages.push({
                        type: "notification",
                        user: notif.title || "闲鱼用户",
                        content: notif.content,
                        id: key
                    });
                }
            }
        }
    } catch (e) {
        log("通知检查失败: " + e);
    }

    // 方法2：如果在闲鱼聊天界面，直接获取消息
    if (isXianyuActive()) {
        try {
            let messages = getChatMessages();
            for (let msg of messages) {
                let key = "chat_" + msg.user;
                if (!lastMessages[key] || lastMessages[key] != msg.content) {
                    newMessages.push(msg);
                }
            }
        } catch (e) {
            log("聊天消息检查失败: " + e);
        }
    }

    return newMessages;
}

// ========== 获取通知栏消息 ==========
function getNotifications() {
    let notifications = [];
    try {
        let notificationService = context.getSystemService(context.NOTIFICATION_SERVICE);
        let bars = notificationService.getActiveNotifications();
        for (let i = 0; i < bars.length; i++) {
            let bar = bars[i];
            let notif = bar.getNotification();
            let extras = notif.extras;
            notifications.push({
                id: bar.getId(),
                packageName: bar.getPackageName(),
                title: extras.getCharSequence("android.title") || "",
                content: extras.getCharSequence("android.text") || ""
            });
        }
    } catch (e) {
        // 某些ROM可能不允许访问通知
    }
    return notifications;
}

// ========== 获取聊天消息 ==========
function getChatMessages() {
    let messages = [];
    try {
        let root = auto.service.getRootInActiveWindow();
        if (!root) return messages;

        // 查找聊天内容区域 - 不同的闲鱼版本可能使用不同的className
        let selectors = [
            className("android.widget.TextView"),
            className("android.widget.EditText"),
            text => text.startsWith("{")
        ];

        let nodes = root.findAll(className("android.widget.TextView"));
        for (let i = 0; i < nodes.size(); i++) {
            let node = nodes.get(i);
            try {
                let text = node.getText();
                if (!text) continue;

                let content = text.toString().trim();
                // 过滤：太短不行，太长不行，包含URL不行
                if (content.length < 2 || content.length > 500) continue;
                if (content.includes("http://") || content.includes("https://")) continue;

                // 获取位置信息
                let bounds = new android.graphics.Rect();
                node.getBoundsInScreen(bounds);

                // 右侧区域（自己发送的）或左侧区域（收到的）
                let screenWidth = context.getResources().getDisplayMetrics().widthPixels;
                let isReceived = bounds.centerX() < screenWidth * 0.5;

                if (!isReceived) continue; // 只处理收到的消息

                messages.push({
                    type: "chat",
                    user: "当前聊天用户",
                    content: content,
                    id: content.substring(0, 50)
                });
            } catch (e) {}
            node.recycle();
        }
        root.recycle();
    } catch (e) {
        logError("获取聊天消息失败: " + e);
    }
    return messages;
}

// ========== 发送消息到服务器 ==========
function forwardToServer(user, content, msgType) {
    try {
        // 使用专门的电话消息接口
        let url = CONFIG.serverUrl + "/api/customer-service/phone/message";
        let body = JSON.stringify({
            user_id: user,
            content: content,
            device_id: CONFIG.deviceId
        });

        let response = http.post(url, body, {
            headers: { "Content-Type": "application/json" },
            timeout: 10000
        });

        if (response.statusCode == 200) {
            let data = JSON.parse(response.body.string());
            log("消息已转发: " + user + " -> " + content.substring(0, 30) + "...");
            processedCount++;
            return true;
        } else {
            logError("转发失败: " + response.statusCode);
            return false;
        }
    } catch (e) {
        logError("转发异常: " + e);
        return false;
    }
}

// ========== 获取AI回复（已集成到phone/message接口中）==========
// AI处理是异步的，phone/message接口会自动触发process_queue

// ========== 主监控循环 ==========
function startMonitoring() {
    if (isRunning) {
        log("已经在运行中");
        return;
    }

    // 检查权限
    if (!auto.service) {
        logError("请先开启辅助功能权限");
        dialogs.confirm({
            title: "需要权限",
            content: "此脚本需要辅助功能权限。\n\n设置 → 无障碍 → AutoJS → 开启",
            positiveText: "确定"
        });
        return;
    }

    isRunning = true;
    log("开始监控闲鱼消息...");
    toast("闲鱼消息监控已启动");

    // 启动后台线程
    threads.start(function() {
        while (isRunning) {
            try {
                // 检查是否有新消息
                let newMessages = checkNewMessages();

                for (let msg of newMessages) {
                    let key = msg.id;
                    if (lastMessages[key]) continue; // 跳过已处理的

                    // 标记已处理
                    lastMessages[key] = msg.content;

                    // 转发到服务器
                    log("收到新消息: " + msg.user + " -> " + msg.content.substring(0, 30));
                    let success = forwardToServer(msg.user, msg.content, msg.type);

                    if (success) {
                        // 触发AI处理（异步，不等待回复）
                        threads.start(function() {
                            sleep(1000); // 等待1秒让AI处理
                            getAIReply(msg.user);
                        });
                    }
                }

                // 定期清理过期的消息记录
                if (processedCount % 50 == 0 && processedCount > 0) {
                    // 保留最新的100条
                    let keys = Object.keys(lastMessages);
                    if (keys.length > 100) {
                        let toDelete = keys.slice(0, keys.length - 100);
                        for (let k of toDelete) {
                            delete lastMessages[k];
                        }
                    }
                }

            } catch (e) {
                logError("监控异常: " + e);
            }

            sleep(CONFIG.pollInterval);
        }
        log("监控已停止");
    });

    // 显示状态
    let statusThread = threads.start(function() {
        while (isRunning) {
            sleep(10000);
            if (isRunning) {
                toast("闲鱼监控运行中，已处理 " + processedCount + " 条消息");
            }
        }
    });
}

function stopMonitoring() {
    isRunning = false;
    log("停止监控...");
    toast("闲鱼消息监控已停止");
}

// ========== 手动测试 ==========
function testForward() {
    let testUser = "测试用户_" + Date.now();
    let testContent = "你好，我想买票";

    log("发送测试消息...");
    let success = forwardToServer(testUser, testContent, "test");

    if (success) {
        toast("测试消息发送成功，AI正在处理...");
        log("测试消息发送成功");

        // 等待AI处理
        sleep(3000);
        toast("AI处理完成，请查看服务器日志");
    } else {
        toast("测试消息发送失败，请检查服务器连接");
        logError("测试消息发送失败");
    }
}

// ========== 启动 ==========
function main() {
    log("=".repeat(50));
    log("闲鱼消息监控");
    log("服务器: " + CONFIG.serverUrl);
    log("设备ID: " + CONFIG.deviceId);
    log("=".repeat(50));

    let choice = dialogs.select("选择操作", [
        "1. 开始监控",
        "2. 停止监控",
        "3. 发送测试消息",
        "4. 退出"
    ]);

    switch (choice) {
        case 0:
            startMonitoring();
            break;
        case 1:
            stopMonitoring();
            break;
        case 2:
            testForward();
            break;
        case 3:
        default:
            stopMonitoring();
            exit();
            break;
    }
}

main();