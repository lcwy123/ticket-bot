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

// 发送日志到服务器
function sendLog(level, msg) {
    if (ws && isConnected) {
        try {
            ws.send(JSON.stringify({
                type: "log",
                level: level,
                message: "[" + TAG + "] " + msg,
                timestamp: Date.now()
            }));
        } catch (e) {}
    }
}

function log(msg) {
    console.log("[" + TAG + "] " + msg);
    sendLog("DEBUG", msg);
}

function logError(msg) {
    console.error("[" + TAG + "] ERROR: " + msg);
    toast("[" + TAG + "] ERROR: " + msg);
    sendLog("ERROR", msg);
}

// ========== 控件树遍历工具 ==========
let UITree = {
    // 获取当前窗口的根节点
    getRoot: function() {
        try {
            // auto.rootInActiveWindow 返回窗口根节点（UiObject），
            // selector().findOne() 可能只匹配到单个元素而非整棵树
            var root = auto.rootInActiveWindow;
            if (root) return root;
        } catch (e) {}
        try {
            return auto.service.getRootInActiveWindow();
        } catch (e) {}
        try {
            return selector().findOne();
        } catch (e) {}
        return null;
    },

    // 判断当前页面是否包含指定文本（用于页面验证）
    // 如 isOnPage("消息") 检查是否在消息列表，isOnPage("首页") 检查是否在首页
    isOnPage: function(keyword) {
        try {
            let elem = text(keyword).findOne(1000);
            if (elem) return true;
            elem = desc(keyword).findOne(500);
            return elem != null;
        } catch (e) {
            return false;
        }
    },

    // 安全获取属性值（兼容 UiObject 和 AccessibilityNodeInfo）
    _safeProp: function(node, propName, methodName) {
        try {
            var v = node[propName];
            if (typeof v === "function") v = v.call(node);
            return v;
        } catch (e) {
            if (methodName) {
                try { return node[methodName](); } catch (e2) {}
            }
            return null;
        }
    },

    _safeChildCount: function(node) {
        try {
            var v = node.childCount;
            if (typeof v === "function") v = v.call(node);
            if (typeof v === "number") return v;
        } catch (e) {}
        try { return node.getChildCount(); } catch (e) {}
        return 0;
    },

    _safeGetChild: function(node, index) {
        try { return node.child(index); } catch (e) {}
        try { return node.getChild(index); } catch (e) {}
        return null;
    },

    // 安全获取 bounds 矩形
    _safeBounds: function(node) {
        try {
            var b = node.bounds;
            if (typeof b === "function") b = b.call(node);
            if (b && typeof b === "object") return {
                left: b.left, top: b.top, right: b.right, bottom: b.bottom,
                cx: (b.left + b.right) / 2, cy: (b.top + b.bottom) / 2
            };
        } catch (e) {}
        try {
            var rect = node.getBounds();
            if (typeof rect === "function") rect = rect.call(node);
            if (rect && typeof rect === "object") return {
                left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
                cx: (rect.left + rect.right) / 2, cy: (rect.top + rect.bottom) / 2
            };
        } catch (e) {}
        return null;
    },

    // 打印当前界面所有文本（调试用）
    dumpTexts: function() {
        let root = this.getRoot();
        if (!root) { log("dumpTexts: 无法获取根节点"); return; }
        let all = [];
        this._collectAll(root, 0, all);
        log("====== 界面控件树 (共 " + all.length + " 个节点) ======");
        for (let i = 0; i < Math.min(all.length, 80); i++) {
            let n = all[i];
            let label = n.text || n.desc || "";
            let extra = "";
            if (n.text && n.desc && n.text !== n.desc) extra = " desc='" + n.desc.substring(0, 20) + "'";
            // 打印所有有文本/描述/可点击/可滚动的节点，text为空也显示 className
            if (label.length > 0 || n.clickable || n.scrollable) {
                log("  [" + n.depth + "] " + (n.className || "").split(".").pop()
                    + (n.clickable ? " [可点击]" : "")
                    + (n.scrollable ? " [可滚动]" : "")
                    + " text='" + (label.length > 50 ? label.substring(0, 50) : label) + "'"
                    + extra);
            }
        }
        log("====== 控件树打印完毕 ======");
    },

    // 内部：递归收集节点信息（纯数据，仅用于 dumpTexts/extractChatMessages）
    _collectAll: function(node, depth, result) {
        if (!node || depth > 40) return;
        try {
            result.push({
                depth: depth,
                text: (this._safeProp(node, "text") || "").toString(),
                desc: (this._safeProp(node, "desc", "getContentDescription") || "").toString(),
                className: (this._safeProp(node, "className", "getClassName") || "").toString(),
                clickable: this._safeProp(node, "clickable", "isClickable"),
                scrollable: this._safeProp(node, "scrollable", "isScrollable"),
                childCount: this._safeChildCount(node),
                bounds: this._safeBounds(node)
            });
            var cc = this._safeChildCount(node);
            for (var i = 0; i < cc; i++) {
                var child = this._safeGetChild(node, i);
                if (child) this._collectAll(child, depth + 1, result);
            }
        } catch (e) {}
    },

    // 向上查找可点击的祖先节点（返回真实 UiObject）
    findClickableAncestor: function(node) {
        if (!node) return null;
        try {
            if (node.clickable) return node;
            let p = node.parent;
            if (p) return this.findClickableAncestor(p);
        } catch (e) {}
        return node;
    },

    // 从聊天界面提取消息文本
    extractChatMessages: function() {
        let root = this.getRoot();
        if (!root) return [];

        let all = [];
        this._collectAll(root, 0, all);

        var uiKeywords = [
            "闲鱼", "消息", "搜索", "发布", "我的", "首页",
            "发送", "图片", "拍照", "语音", "表情", "红包", "转账",
            "关注", "粉丝", "动态", "卖出", "买到", "评价",
            "以上为历史消息", "系统消息", "加载更多",
            "输入", "说点什么", "文明发言", "请输入",
            "头像", "返回", "更多", "更多选择", "立即购买",
            "语音按钮", "表情按钮", "商品图片", "商品信息",
            "想跟TA说点什么"
        ];

        // 计算屏幕上边界（导航栏下方）和下边界（输入区上方）
        var screenBottom = 0;
        var screenTop = 9999;
        for (var si = 0; si < all.length; si++) {
            if (all[si].bounds) {
                if (all[si].bounds.bottom > screenBottom) screenBottom = all[si].bounds.bottom;
                if (all[si].bounds.top < screenTop) screenTop = all[si].bounds.top;
            }
        }
        var topCutoff = screenTop + (screenBottom - screenTop) * 0.12;    // 顶部12% = 导航栏
        var bottomCutoff = screenBottom - (screenBottom - screenTop) * 0.15; // 底部15% = 输入区

        var messages = [];
        for (var j = 0; j < all.length; j++) {
            var t = all[j].text || all[j].desc || "";
            if (t.length < 2) continue;
            // 纯数字且≤3位（时间戳）
            if (t.length <= 3 && /^\d+$/.test(t)) continue;
            // 时间/日期格式
            if (/^[\d]{1,2}:[\d]{2}$/.test(t.trim())) continue;
            if (/^[\d]{4}[-/][\d]{2}[-/][\d]{2}$/.test(t.trim())) continue;
            if (/^[\d]{2}[-/][\d]{2}$/.test(t.trim())) continue;
            // 系统标签
            if (t === "红点提醒" || t === "通知消息" || t === "互动消息" || t === "热门活动") continue;
            if (t.indexOf("未读") >= 0) continue;

            // 精确匹配 UI 关键词则跳过
            var isUI = false;
            for (var k = 0; k < uiKeywords.length; k++) {
                if (t === uiKeywords[k] || (uiKeywords[k].length >= 3 && t.indexOf(uiKeywords[k]) >= 0)) {
                    isUI = true;
                    break;
                }
            }
            if (isUI) continue;

            // 位置过滤：只在屏幕中间区域（排除顶部导航栏和底部输入区）
            if (all[j].bounds) {
                var b = all[j].bounds;
                if (b.top < topCutoff || b.top > bottomCutoff) continue;
            }

            // 聊天消息在较深层级
            if (all[j].depth < 10) continue;

            messages.push(t);
        }

        return messages;
    }
};

// ========== 闲鱼导航流程 ==========
let XianyuNavigator = {

    // 确保闲鱼在前台，且主页已完全加载（广告结束后）
    ensureAppForeground: function() {
        log("[导航] 启动闲鱼...");
        launch("com.taobao.idlefish");
        sleep(2000);

        // Step 1: 确保 APP 已在前台
        var appReady = false;
        for (var retry = 0; retry < 5; retry++) {
            var pkg = currentPackage();
            log("[导航] 当前包名: " + pkg);
            if (pkg === XIANYU_PACKAGE) {
                appReady = true;
                break;
            }
            sleep(2000);
        }
        if (!appReady) {
            logError("[导航] 闲鱼未能启动到前台");
            return false;
        }

        // Step 2: 等待主页加载完成（开屏广告可能持续几秒）
        // 主页特征：底部tab栏包含"首页"/"消息"/"我的"等，或"卖闲置"大按钮
        log("[导航] 等待主页加载...");
        for (var w = 0; w < 8; w++) {
            // 检查主页特征元素是否出现
            var sellBtn = text("卖闲置").findOne(1000);
            // 或者检查底部导航栏
            var bottomNav = text("消息").findOne(1000);
            var myTab = text("我的").findOne(1000);

            if (sellBtn || (bottomNav && myTab)) {
                log("[导航] 主页已加载 (等待" + (w + 1) + "秒)");
                return true;
            }

            // 如果还在广告页面，尝试跳过
            var skipBtn = textContains("跳过").findOne(500);
            if (skipBtn) {
                log("[导航] 检测到广告跳过按钮，点击...");
                try { skipBtn.click(); } catch (e) {}
            }

            sleep(1000);
        }

        // 最后再试一次：用控件树检查
        var root = UITree.getRoot();
        if (root) {
            var all = [];
            UITree._collectAll(root, 0, all);
            for (var i = 0; i < all.length; i++) {
                var t = all[i].text || "";
                if (t === "卖闲置" || t === "消息" || t === "我的") {
                    log("[导航] 主页已加载（控件树检测）");
                    return true;
                }
            }
        }

        log("[导航] 主页可能未完全加载，继续尝试...");
        return true; // 继续尝试，不阻塞流程
    },

    // 验证当前是否在指定页面（检查左上角标题）
    verifyPage: function(pageTitle) {
        let found = text(pageTitle).findOne(2000);
        if (found) {
            log("[验证] 已在" + pageTitle + "页面");
            return true;
        }
        found = desc(pageTitle).findOne(500);
        if (found) {
            log("[验证] 已在" + pageTitle + "页面 (desc)");
            return true;
        }
        log("[验证] 未检测到'" + pageTitle + "'，可能不在目标页面");
        return false;
    },

    // 进入消息列表（坐标点击 + 页面验证）
    goToMessageList: function() {
        for (let retry = 0; retry < 3; retry++) {
            log("[导航] 坐标点击消息tab (770, 2270)，第" + (retry + 1) + "次...");
            click(770, 2270);
            sleep(2500);

            if (this.verifyPage("消息")) {
                return true;
            }
            log("[导航] 未进入消息列表，重试...");
        }
        logError("[导航] 多次重试后仍未能进入消息列表");
        return false;
    },

    // 在消息列表中滚动加载更多会话
    scrollMessageList: function() {
        log("[导航] 滚动消息列表加载更多...");
        // 在消息列表区域从下往上滑动
        swipe(540, 1600, 540, 800, 400);
        sleep(1500);
    },

    // 验证是否在目标用户的会话页面（而非消息列表）
    verifyConversation: function(userName) {
        log("[验证] 检查是否已进入会话...");
        sleep(800);

        var root = UITree.getRoot();
        if (!root) return false;
        var all = [];
        UITree._collectAll(root, 0, all);

        // 如果在消息列表，会有"清除未读"或"搜索聊天记录"
        var hasClearUnread = false;
        var hasSearchBar = false;
        var hasInputField = false;
        var hasUserName = false;

        for (var i = 0; i < all.length; i++) {
            var t = all[i].text || all[i].desc || "";
            if (t === "清除未读" || t === "清除未读消息") hasClearUnread = true;
            if (t.indexOf("搜索聊天记录") >= 0) hasSearchBar = true;
            if (t.indexOf("输入") >= 0 || t.indexOf("说点什么") >= 0 || t === "请输入消息") hasInputField = true;
            if (userName && t.indexOf(userName) >= 0 && all[i].depth < 12) hasUserName = true;
        }

        // 在消息列表的标志：有"清除未读"且有搜索栏
        if (hasClearUnread && hasSearchBar) {
            log("[验证] 仍在消息列表页面，未进入会话");
            return false;
        }

        // 在会话页面的标志：有输入框，且深度较浅处有用户名
        if (hasInputField || hasUserName) {
            log("[验证] 已进入会话页面" + (hasUserName ? " (" + userName + ")" : ""));
            return true;
        }

        // 有输入框但没用户名也算进入会话（可能用户名在更浅层）
        if (hasInputField) {
            log("[验证] 检测到输入框，认为已进入会话");
            return true;
        }

        log("[验证] 无法确定当前页面状态");
        return false;
    },

    // 在消息列表中匹配并进入目标会话
    // 先滚动加载更多，再在控件树数据中匹配文本，点击后验证
    findConversation: function(userName) {
        log("[导航] 在消息列表中匹配会话: " + userName);

        // 获取完整控件树数据（最新消息在上方，不需要滚动）
        var root = UITree.getRoot();
        if (!root) {
            logError("[导航] 无法获取控件树");
            return null;
        }
        var all = [];
        UITree._collectAll(root, 0, all);

        // 调试：打印当前界面
        UITree.dumpTexts();

        // 在已采集的树数据中匹配 userName
        var matchIdx = -1;

        // 策略 1: 精确匹配
        for (var i = 0; i < all.length; i++) {
            if (all[i].text === userName || all[i].desc === userName) {
                matchIdx = i;
                log("[匹配] 策略1 精确匹配: [" + all[i].depth + "] " + (all[i].text || all[i].desc));
                break;
            }
        }

        // 策略 2: 包含匹配
        if (matchIdx < 0) {
            for (var k = 0; k < all.length; k++) {
                var t = all[k].text || all[k].desc || "";
                if (t.indexOf(userName) >= 0) {
                    matchIdx = k;
                    log("[匹配] 策略2 包含匹配: [" + all[k].depth + "] " + t);
                    break;
                }
            }
        }

        // 策略 3: 模糊匹配（前半部分）
        if (matchIdx < 0 && userName.length >= 3) {
            var shortName = userName.substring(0, Math.floor(userName.length / 2));
            for (var j = 0; j < all.length; j++) {
                var t2 = all[j].text || all[j].desc || "";
                if (t2.indexOf(shortName) >= 0 && t2.length > 2) {
                    matchIdx = j;
                    log("[匹配] 策略3 模糊匹配: [" + all[j].depth + "] " + t2);
                    break;
                }
            }
        }

        // 如果匹配到了，向上查找可点击祖先并点击
        if (matchIdx >= 0) {
            var targetDepth = all[matchIdx].depth;
            // 从匹配位置往前搜索可点击祖先
            for (var p = matchIdx - 1; p >= 0; p--) {
                if (all[p].clickable && all[p].depth < targetDepth) {
                    var b = all[p].bounds;
                    if (b) {
                        log("[匹配] 找到可点击祖先 depth=" + all[p].depth + " (" + b.cx + "," + b.cy + ")");
                        click(b.cx, b.cy);
                        sleep(2500);
                        // 验证是否进入会话
                        if (this.verifyConversation(userName)) return true;
                        // 没进入，按返回重试
                        log("[匹配] 未进入目标会话，返回重试...");
                        back();
                        sleep(1000);
                    }
                }
            }
            // 如果匹配节点本身可点击
            if (all[matchIdx].clickable) {
                var mb = all[matchIdx].bounds;
                if (mb) {
                    log("[匹配] 匹配节点自身可点击: (" + mb.cx + "," + mb.cy + ")");
                    click(mb.cx, mb.cy);
                    sleep(2500);
                    if (this.verifyConversation(userName)) return true;
                    back();
                    sleep(1000);
                }
            }
        }

        // 策略 4: 兜底 — 逐个尝试会话行，验证是否进入目标会话
        log("[匹配] 文本匹配失败，逐个尝试会话行...");
        for (var x = 0; x < all.length; x++) {
            if (all[x].clickable && all[x].depth >= 4 && all[x].childCount >= 1) {
                var bx = all[x].bounds;
                if (bx && bx.cy > 200) {
                    log("[匹配] 策略4 尝试: depth=" + all[x].depth + " (" + bx.cx + "," + bx.cy + ")");
                    click(bx.cx, bx.cy);
                    sleep(2500);
                    if (this.verifyConversation(userName)) return true;
                    // 返回消息列表
                    back();
                    sleep(1000);
                }
            }
        }

        logError("[导航] 未找到匹配的会话");
        return null;
    },

    // 从当前聊天界面提取完整消息
    readFullMessage: function() {
        log("[导航] 提取聊天消息...");
        sleep(1000); // 等待消息加载

        // 先验证在会话页面（不是消息列表）
        var root = UITree.getRoot();
        if (!root) return null;
        var all = [];
        UITree._collectAll(root, 0, all);

        // 检查是否仍在消息列表
        for (var ci = 0; ci < all.length; ci++) {
            var ct = all[ci].text || "";
            if (ct === "清除未读" || ct.indexOf("搜索聊天记录") >= 0) {
                log("[导航] 仍在消息列表，放弃提取");
                return null;
            }
        }

        UITree.dumpTexts();

        var messages = UITree.extractChatMessages();
        log("[导航] 提取到 " + messages.length + " 条候选消息");

        if (messages.length > 0) {
            // 去重
            var unique = [];
            for (var u = 0; u < messages.length; u++) {
                if (unique.indexOf(messages[u]) < 0) {
                    unique.push(messages[u]);
                }
            }
            log("[导航] 去重后 " + unique.length + " 条消息");

            // 打印最近 5 条
            for (var p = 0; p < Math.min(unique.length, 5); p++) {
                log("[导航]   msg[" + p + "]: " + unique[p].substring(0, 60));
            }

            // 返回最后一条作为最新消息
            var lastMsg = unique[unique.length - 1];
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

// ========== 辅助函数 ==========
function repeatStr(s, n) {
    var r = "";
    for (var i = 0; i < n; i++) r += s;
    return r;
}

// ========== 启动 ==========
function main() {
    var sep = repeatStr("=", 50);
    log(sep);
    log("闲鱼 Agent WebSocket 客户端 (AutoJS6)");
    log("服务器: " + CONFIG.wsUrl);
    log("通知监控: " + (CONFIG.enableNotificationMonitor ? "启用" : "禁用"));
    log(sep);

    toast("正在连接服务器...");
    connect();

    if (CONFIG.enableNotificationMonitor) {
        threads.start(function() {
            sleep(2000);
            var started = startNotificationListener();
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

try {
    main();
} catch (e) {
    console.error("[XianyuAgent] 启动失败: " + e);
    toast("[XianyuAgent] 启动失败: " + e);
}
