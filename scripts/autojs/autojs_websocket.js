/**
 * AutoJS6 WebSocket 客户端脚本
 * 支持设备控制 + 闲鱼消息通知监控 + 无障碍控件树导航提取完整消息
 */

// ========== 配置 ==========
let CONFIG = {
    wsUrl: "ws://121.43.146.124:8000/api/agent/device/ws/my_phone",
    debugMode: true,
    enableNotificationMonitor: true
};

// ========== 常量 ==========
const XIANYU_PACKAGE = "com.taobao.idlefish";

// ========== 全局状态 ==========
let ws = null;
let isConnected = false;
let reconnectTimer = null;
let seenNotifications = new Set();
let processedCount = 0;
let processingLock = false; // 防止多个通知同时触发导航

// ========== 日志 ==========
let TAG = "XianyuAgent";

function log(msg) {
    if (CONFIG.debugMode) {
        console.log("[" + TAG + "] " + msg);
    }
}

function logError(msg) {
    console.error("[" + TAG + "] ERROR: " + msg);
    toast("[" + TAG + "] ERROR: " + msg);
}

// ========== 控件树遍历工具 ==========
let UITree = {
    // 获取当前窗口的根节点
    getRoot: function() {
        try {
            let root = selector().findOne();
            return root;
        } catch (e) {
            log("getRoot 失败: " + e);
            return null;
        }
    },

    // 递归收集所有节点的文本信息（带深度）
    collectAll: function(node, depth, result) {
        if (!node || depth > 40) return;
        try {
            let info = {
                depth: depth,
                text: (node.text() || "").toString(),
                desc: (node.desc() || "").toString(),
                className: (node.className() || "").toString(),
                clickable: node.clickable(),
                scrollable: node.scrollable(),
                childCount: node.childCount()
            };
            result.push(info);

            for (let i = 0; i < node.childCount(); i++) {
                let child = node.child(i);
                if (child) {
                    this.collectAll(child, depth + 1, result);
                }
            }
        } catch (e) {
            // 节点可能已失效，跳过
        }
    },

    // 打印当前界面所有文本（调试用）
    dumpTexts: function() {
        let root = this.getRoot();
        if (!root) { log("dumpTexts: 无法获取根节点"); return; }
        let all = [];
        this.collectAll(root, 0, all);
        log("====== 界面控件树 (共 " + all.length + " 个节点) ======");
        for (let i = 0; i < Math.min(all.length, 50); i++) {
            let node = all[i];
            let label = node.text || node.desc || "";
            if (label.length > 0 || node.clickable) {
                log("  [" + node.depth + "] " + node.className.split(".").pop()
                    + (node.clickable ? " [可点击]" : "")
                    + (node.scrollable ? " [可滚动]" : "")
                    + " text='" + label.substring(0, 40) + "'");
            }
        }
        log("====== 控件树打印完毕 ======");
    },

    // 在控件树中查找 clickable=true 且自身或子节点包含指定文本的节点
    // 返回第一个匹配的节点（用于点击进入对话）
    findClickableContaining: function(node, searchText) {
        if (!node || !searchText) return null;
        try {
            // 检查当前节点的 text/desc 是否匹配
            let t = (node.text() || "").toString();
            let d = (node.desc() || "").toString();

            // 如果当前节点 clickable 且文本包含搜索词，返回
            if (node.clickable() && (t.indexOf(searchText) >= 0 || d.indexOf(searchText) >= 0)) {
                return node;
            }

            // 向下递归搜索
            for (let i = 0; i < node.childCount(); i++) {
                let child = node.child(i);
                if (!child) continue;
                let found = this.findClickableContaining(child, searchText);
                if (found) return found;
            }
        } catch (e) {}
        return null;
    },

    // 查找距离根节点最近的 clickable 祖先（用于点击一个文本后需要点击其外层容器）
    findClickableAncestor: function(node) {
        if (!node) return null;
        try {
            if (node.clickable()) return node;
            let p = node.parent();
            if (p) return this.findClickableAncestor(p);
        } catch (e) {}
        return node; // 找不到就返回自身
    },

    // 在 scrollable 容器内，收集所有 text 不为空的子节点文本
    collectTextsInScrollable: function(node, result) {
        if (!node) return;
        try {
            let t = (node.text() || "").toString();
            if (t.length > 0) {
                result.push(t);
            }
            for (let i = 0; i < node.childCount(); i++) {
                let child = node.child(i);
                if (child) {
                    this.collectTextsInScrollable(child, result);
                }
            }
        } catch (e) {}
    },

    // 从聊天界面提取消息内容
    // 策略：找到可滚动的消息列表 → 收集所有文本 → 过滤出真正的消息
    extractChatMessages: function() {
        let root = this.getRoot();
        if (!root) return [];

        // 收集所有文本节点
        let allNodes = [];
        this.collectAll(root, 0, allNodes);

        // 过滤策略：
        // 1. 跳过深度太浅的（toolbar 区域，通常 depth < 5）
        // 2. 跳过 editable 节点（输入框）
        // 3. 跳过过短的文本（时间戳、数字角标等，长度 <= 3）
        // 4. 跳过明显的 UI 固定文本
        let uiKeywords = [
            "闲鱼", "消息", "搜索", "发布", "我的", "首页", "输入",
            "发送", "图片", "拍照", "语音", "表情", "红包", "转账",
            "关注", "粉丝", "动态", "卖出", "买到", "评价",
            "以上为历史消息", "系统消息", "加载更多"
        ];

        let messages = [];
        for (let i = 0; i < allNodes.length; i++) {
            let node = allNodes[i];
            let t = node.text;

            // 跳过空文本
            if (!t || t.length === 0) continue;
            // 跳过太短的（时间、角标）
            if (t.length <= 2 && /^[\d:：\-/\s]+$/.test(t)) continue;
            // 跳过纯数字
            if (/^\d+$/.test(t) && t.length <= 3) continue;
            // 跳过 UI 关键词
            let isUI = false;
            for (let k = 0; k < uiKeywords.length; k++) {
                if (t === uiKeywords[k]) { isUI = true; break; }
            }
            if (isUI) continue;
            // 跳过 toolbar 区域（深度太浅）
            if (node.depth < 6 && node.className.indexOf("Toolbar") < 0) continue;

            messages.push(t);
        }

        return messages;
    }
};

// ========== 闲鱼导航流程 ==========
let XianyuNavigator = {

    // 确保闲鱼在前台
    ensureAppForeground: function() {
        log("[导航] 启动闲鱼...");
        launch("com.taobao.idlefish");
        sleep(2500);

        for (let retry = 0; retry < 3; retry++) {
            let pkg = currentPackage();
            log("[导航] 当前包名: " + pkg);
            if (pkg === XIANYU_PACKAGE) return true;
            sleep(2000);
        }
        logError("[导航] 闲鱼未能启动到前台");
        return false;
    },

    // 进入消息列表
    goToMessageList: function() {
        log("[导航] 进入消息列表...");

        // 策略 1: 通过 desc="消息" 查找（最可靠）
        let tab = desc("消息").findOne(3000);
        if (tab) {
            log("[导航] 策略1: desc='消息' 找到，点击");
            tab.click();
            sleep(2000);
            return true;
        }

        // 策略 2: 通过 text="消息" 查找
        tab = text("消息").findOne(2000);
        if (tab) {
            log("[导航] 策略2: text='消息' 找到，点击");
            tab.click();
            sleep(2000);
            return true;
        }

        // 策略 3: 遍历控件树，找 clickable 且含"消息"文本的元素
        let root = UITree.getRoot();
        if (root) {
            let found = UITree.findClickableContaining(root, "消息");
            if (found) {
                log("[导航] 策略3: 控件树中找到含'消息'的可点击元素");
                found.click();
                sleep(2000);
                return true;
            }
        }

        // 策略 4: 坐标点击（底部导航栏"消息"位置，通常是第 2 个 tab）
        // 1080x2400 屏幕，底部导航约在 y=2200-2350，"消息"约在 x=200-350
        log("[导航] 策略4: 尝试坐标点击底部消息tab...");
        click(270, 2280);
        sleep(2500);

        // 验证是否进入了消息列表（检查界面是否有"消息"标题或会话列表特征）
        root = UITree.getRoot();
        if (root) {
            let all = [];
            UITree.collectAll(root, 0, all);
            for (let i = 0; i < all.length; i++) {
                let t = all[i].text;
                if (t && (t === "消息" || t.indexOf("聊天") >= 0 || t.indexOf("会话") >= 0)) {
                    log("[导航] 策略4: 验证成功，已进入消息列表");
                    return true;
                }
            }
        }

        logError("[导航] 所有策略均未能进入消息列表");
        return false;
    },

    // 在消息列表中匹配并找到目标会话
    findConversation: function(userName) {
        log("[导航] 在消息列表中匹配会话: " + userName);

        // 先 dump 当前界面文本用于调试
        UITree.dumpTexts();

        let root = UITree.getRoot();
        if (!root) { logError("[导航] 无法获取消息列表根节点"); return null; }

        // 收集所有节点
        let allNodes = [];
        UITree.collectAll(root, 0, allNodes);

        // 策略 1: 在所有节点中精确匹配 userName
        let candidates = [];
        for (let i = 0; i < allNodes.length; i++) {
            let node = allNodes[i];
            let t = node.text;
            if (t && t === userName) {
                // 找到精确匹配的文本节点，取其 clickable 祖先
                candidates.push({ node: allNodes[i], type: "exact", score: 100 });
            }
        }

        // 策略 2: 包含匹配
        if (candidates.length === 0) {
            for (let i = 0; i < allNodes.length; i++) {
                let node = allNodes[i];
                let t = node.text;
                if (t && t.length >= userName.length && t.indexOf(userName) >= 0) {
                    candidates.push({ node: allNodes[i], type: "contains", score: 80 });
                }
            }
        }

        // 策略 3: 模糊匹配（用户名可能被截断或有前后缀）
        if (candidates.length === 0 && userName.length >= 3) {
            let shortName = userName.substring(0, Math.floor(userName.length / 2));
            for (let i = 0; i < allNodes.length; i++) {
                let node = allNodes[i];
                let t = node.text;
                if (t && t.indexOf(shortName) >= 0 && t.length > 2) {
                    candidates.push({ node: allNodes[i], type: "partial", score: 50 });
                }
            }
        }

        // 策略 4: 尝试匹配通知内容中的关键词
        if (candidates.length === 0) {
            log("[导航] 文本匹配失败，尝试找第一条未读会话...");
            // 通常新消息在最上面，找第一个看起来像用户名的可点击行
            for (let i = 0; i < allNodes.length; i++) {
                let node = allNodes[i];
                if (node.clickable && node.depth >= 6 && node.childCount >= 2) {
                    candidates.push({ node: allNodes[i], type: "firstClickable", score: 10 });
                    break;
                }
            }
        }

        if (candidates.length === 0) {
            logError("[导航] 未找到任何匹配的会话");
            return null;
        }

        // 选最佳候选，找到其可点击祖先
        let best = candidates[0];
        log("[导航] 匹配结果: type=" + best.type + ", score=" + best.score + ", text='" + best.node.text + "'");

        // 从匹配节点向上找到可点击的父节点
        let target = best.node;
        try {
            for (let up = 0; up < 5; up++) {
                if (target.clickable()) break;
                let p = target.parent();
                if (!p) break;
                target = p;
            }
        } catch (e) {}

        if (!target.clickable()) {
            // 如果还是不可点击，找最近的可点击兄弟/祖先
            log("[导航] 匹配节点不可点击，搜索可点击祖先...");
            // 直接在节点树上找
            for (let i = 0; i < allNodes.length; i++) {
                if (allNodes[i].clickable && allNodes[i].depth < best.node.depth) {
                    // 检查这个可点击节点是否包含匹配文本
                    let checkText = allNodes[i].text;
                    if (checkText && checkText.indexOf(userName) < 0 && checkText.indexOf("消息") < 0) {
                        // 可能是容器，直接用坐标点击
                        let bounds = target.bounds();
                        if (bounds) {
                            click(bounds.centerX(), bounds.centerY());
                            sleep(2000);
                            return true;
                        }
                    }
                }
            }
            return null;
        }

        log("[导航] 点击目标会话: clickable=" + target.clickable() + ", text='" + (target.text() || "") + "'");
        target.click();
        sleep(2000);
        return true;
    },

    // 从当前聊天界面提取完整消息
    readFullMessage: function() {
        log("[导航] 提取聊天消息...");
        sleep(1000); // 等待消息加载

        UITree.dumpTexts();

        let messages = UITree.extractChatMessages();
        log("[导航] 提取到 " + messages.length + " 条候选消息");

        if (messages.length > 0) {
            // 去重并取最后几条作为新消息
            let unique = [];
            for (let i = 0; i < messages.length; i++) {
                if (unique.indexOf(messages[i]) < 0) {
                    unique.push(messages[i]);
                }
            }
            log("[导航] 去重后 " + unique.length + " 条消息");

            // 打印前 5 条
            for (let i = 0; i < Math.min(unique.length, 5); i++) {
                log("[导航]   msg[" + i + "]: " + unique[i].substring(0, 60));
            }

            // 返回最后一条作为新消息（最新消息通常在列表末尾）
            let lastMsg = unique[unique.length - 1];
            if (lastMsg && lastMsg.length > 1) {
                return lastMsg;
            }
        }

        return null;
    }
};

// ========== 发送消息到服务器 ==========
function sendToServer(userName, content, source) {
    if (!ws || !isConnected) {
        log("WebSocket未连接，无法发送");
        return false;
    }

    let payload = {
        type: "message",
        user_id: userName || "闲鱼用户",
        content: content || "",
        source: source || "xianyu_app",
        timestamp: Date.now()
    };

    try {
        ws.send(JSON.stringify(payload));
        log("已发送到服务器: " + userName + " | " + (content || "").substring(0, 40));
        return true;
    } catch (e) {
        logError("发送失败: " + e);
        return false;
    }
}

// ========== 通知处理主流程 ==========
function processNotification(userName, notifyContent) {
    if (processingLock) {
        log("正在处理上一条通知，跳过");
        return;
    }
    processingLock = true;

    try {
        log("========================================");
        log("开始处理通知: " + userName);
        log("通知内容预览: " + (notifyContent || "").substring(0, 50));
        log("========================================");

        // Step 1: 确保闲鱼在前台
        if (!XianyuNavigator.ensureAppForeground()) {
            logError("Step 1 失败: 无法启动闲鱼");
            sendToServer(userName, notifyContent, "notification_fallback");
            return;
        }
        log("Step 1 OK: 闲鱼已在前台");

        // Step 2: 进入消息列表
        if (!XianyuNavigator.goToMessageList()) {
            logError("Step 2 失败: 无法进入消息列表");
            sendToServer(userName, notifyContent, "notification_fallback");
            return;
        }
        log("Step 2 OK: 已进入消息列表");

        // Step 3: 匹配并进入目标会话
        if (!XianyuNavigator.findConversation(userName)) {
            logError("Step 3 失败: 未找到会话");
            sendToServer(userName, notifyContent, "notification_fallback");
            return;
        }
        log("Step 3 OK: 已进入会话");

        // Step 4: 提取完整消息
        let fullMessage = XianyuNavigator.readFullMessage();
        if (fullMessage && fullMessage.length > 1) {
            log("Step 4 OK: 提取到完整消息: " + fullMessage);
            sendToServer(userName, fullMessage, "xianyu_app");
        } else {
            log("Step 4 降级: 未能提取完整消息，发送通知原文");
            sendToServer(userName, notifyContent, "notification_fallback");
        }

    } catch (e) {
        logError("通知处理异常: " + e);
        sendToServer(userName, notifyContent, "notification_fallback");
    } finally {
        // Step 5: 返回
        try {
            sleep(500);
            back();
            sleep(500);
        } catch (e) {}
        processingLock = false;
        log("========== 通知处理完成 ==========");
    }
}

// ========== 通知事件监听 ==========
function startNotificationListener() {
    try {
        log("开启通知监听...");
        events.observeNotification();
        log("通知观察已开启");

        events.onNotification(function(notification) {
            try {
                let packageName = notification.packageName;
                let title = (notification.title || "").toString();
                let content = (notification.text || "").toString();

                // 只处理闲鱼的通知
                if (packageName !== XIANYU_PACKAGE) return;
                if (!title && !content) return;

                log("收到闲鱼通知: title=" + title + ", content=" + content.substring(0, 50));

                // 去重
                let key = title + "_" + content;
                if (seenNotifications.has(key)) return;
                seenNotifications.add(key);
                processedCount++;

                // 限制集合大小
                if (seenNotifications.size > 500) {
                    let arr = Array.from(seenNotifications);
                    seenNotifications = new Set(arr.slice(-200));
                }

                // 启动后台线程处理：打开APP → 导航 → 提取 → 上传
                threads.start(function() {
                    processNotification(title, content);
                });

            } catch (e) {
                logError("通知回调异常: " + e);
            }
        });

        log("通知事件监听已注册");
        return true;

    } catch (e) {
        logError("开启通知监听失败: " + e);
        return false;
    }
}

// ========== 辅助功能服务（设备控制用） ==========
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
        try { return auto.service != null; } catch (e) { return false; }
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
            return { success: result, action: "swipe" };
        } catch (e) {
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
        this._captureGranted = granted;
        if (!granted) toast("截图权限申请失败，请手动授权");
        return granted;
    },

    takeScreenshot: function() {
        try {
            if (!this._captureGranted) this.requestCapturePermission();
            if (!this._captureGranted) return { success: false, error: "截图权限未授权" };
            sleep(500);
            let img = captureScreen();
            if (img) {
                let path = "/sdcard/autojs_screenshot.png";
                images.save(img, path, "png", 100);
                img.recycle();
                return { success: true, path: path };
            }
            return { success: false, error: "截图失败" };
        } catch (e) {
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
            let elem = textContains(text).findOne(3000);
            if (elem) {
                elem.click();
                return { success: true, action: "find" };
            }
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
    if (isConnected) { log("已经在连接中"); return; }
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
        });

        ws.on(WebSocket.EVENT_TEXT, function(text, ws) {
            log("收到: " + text);
            try {
                let data = JSON.parse(text);
                if (data.type == "command") executeCommand(data);
                else if (data.type == "ping") ws.send(JSON.stringify({ type: "pong", timestamp: Date.now() }));
                else if (data.type == "connected") toast("服务器连接成功");
            } catch (e) {
                logError("解析失败: " + e);
            }
        });

        ws.on(WebSocket.EVENT_CLOSED, function(code, reason, ws) {
            log("WebSocket 关闭. code: " + code);
            isConnected = false;
            ws = null;
            scheduleReconnect();
        });

        ws.on(WebSocket.EVENT_FAILURE, function(err, res, ws) {
            logError("连接失败: " + JSON.stringify(err));
            isConnected = false;
            ws = null;
            scheduleReconnect();
        });

    } catch (e) {
        logError("创建 WebSocket 失败: " + e);
        scheduleReconnect();
    }
}

function scheduleReconnect() {
    if (reconnectTimer) return;
    log("5秒后尝试重连...");
    reconnectTimer = setTimeout(function() {
        reconnectTimer = null;
        connect();
    }, 5000);
}

// ========== 命令执行 ==========
function executeCommand(cmd) {
    log("执行指令: " + cmd.action);
    let result = null;

    try {
        switch (cmd.action) {
            case "click":
            case "tap":
                result = AccessibilityClient.click(cmd.x || 0, cmd.y || 0);
                break;
            case "swipe":
                result = AccessibilityClient.swipe(cmd.x1 || 0, cmd.y1 || 0, cmd.x2 || 0, cmd.y2 || 0, cmd.duration || 500);
                break;
            case "input":
            case "text":
                result = AccessibilityClient.inputText(cmd.text || "");
                break;
            case "back":
                result = AccessibilityClient.pressBack();
                break;
            case "home":
                result = AccessibilityClient.pressHome();
                break;
            case "screenshot":
                result = AccessibilityClient.takeScreenshot();
                break;
            case "getText":
                result = AccessibilityClient.getText();
                break;
            case "find":
                result = AccessibilityClient.findAndClick(cmd.text || "");
                break;
            case "launch":
                result = AccessibilityClient.launchApp(cmd.app || "");
                break;
            case "dumpTree":
                // 新增：dump 控件树（调试用）
                UITree.dumpTexts();
                result = { success: true, action: "dumpTree" };
                break;
            default:
                result = { success: false, error: "未知指令: " + cmd.action };
        }
    } catch (e) {
        result = { success: false, error: "" + e };
    }

    if (ws && isConnected) {
        try {
            ws.send(JSON.stringify({
                type: "result",
                command_id: cmd.id,
                result: result,
                timestamp: Date.now()
            }));
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
    log("通知监控: " + (CONFIG.enableNotificationMonitor ? "启用" : "禁用"));
    log("=".repeat(50));

    toast("正在连接服务器...");
    connect();

    if (CONFIG.enableNotificationMonitor) {
        threads.start(function() {
            sleep(2000);
            let started = startNotificationListener();
            if (started) {
                log("消息通知监控已启动");
                toast("消息通知监控已启动");
            }
        });
    }

    toast("脚本已启动");

    threads.start(function() {
        while (true) {
            sleep(1000);
            if (!isConnected && !reconnectTimer) {
                scheduleReconnect();
            }
        }
    });

    log("脚本已就绪");
}

main();
