/**
 * AutoJS 闲鱼消息监控脚本 (HTTP轮询版)
 * 通过通知栏监控闲鱼消息，HTTP POST到服务器
 */

let TAG = "XianyuMonitor";

// ========== 配置 ==========
let CONFIG = {
    serverUrl: "http://121.43.146.124:8000",
    pollInterval: 2000,
    debugMode: true
};

// ========== 常量 ==========
const XIANYU_PACKAGE = "com.taobao.idlefish";

// ========== 全局状态 ==========
let isRunning = false;
let lastNotifications = {};
let processedCount = 0;

// ========== 日志 ==========
function log(msg) {
    if (CONFIG.debugMode) {
        console.log("[" + TAG + "] " + msg);
    }
}

function logError(msg) {
    console.error("[" + TAG + "] ERROR: " + msg);
}

// ========== 通知栏检查 ==========
function checkNotifications() {
    try {
        let notificationService = context.getSystemService(context.NOTIFICATION_SERVICE);
        let bars = notificationService.getActiveNotifications();

        for (let i = 0; i < bars.length; i++) {
            let bar = bars[i];
            let pkg = bar.getPackageName();
            let notif = bar.getNotification();
            let extras = notif.extras;

            let title = extras.getCharSequence("android.title") || "";
            let content = extras.getCharSequence("android.text") || "";

            // 匹配闲鱼通知
            if (pkg != XIANYU_PACKAGE) continue;
            if (!title && !content) continue;

            let key = bar.getId() + "_" + content;
            if (lastNotifications[key]) continue;

            lastNotifications[key] = true;
            processedCount++;

            log("闲鱼通知: " + title + " | " + content.substring(0, 30));

            // 发送到服务器
            let payload = {
                user_id: title.toString() || "闲鱼用户",
                content: content.toString(),
                device_id: "my_phone"
            };

            try {
                let url = CONFIG.serverUrl + "/api/customer-service/phone/message";
                let body = JSON.stringify(payload);
                let response = http.post(url, body, {
                    headers: { "Content-Type": "application/json" },
                    timeout: 5000
                });
                if (response.statusCode == 200) {
                    log("已转发: " + content.substring(0, 20));
                } else {
                    logError("转发失败: " + response.statusCode);
                }
            } catch (e) {
                logError("发送失败: " + e);
            }
        }
    } catch (e) {
        logError("检查通知失败: " + e);
    }
}

// ========== 主循环 ==========
function main() {
    log("闲鱼消息监控启动");
    toast("闲鱼消息监控启动");

    isRunning = true;

    while (isRunning) {
        checkNotifications();

        if (processedCount > 0 && processedCount % 20 == 0) {
            toast("已处理 " + processedCount + " 条");
        }

        sleep(CONFIG.pollInterval);
    }

    log("监控已停止");
}

// ========== 启动 ==========
function start() {
    if (isRunning) {
        toast("已经在运行");
        return;
    }
    threads.start(main);
    toast("监控线程已启动");
}

function stop() {
    isRunning = false;
    toast("监控已停止");
}

// 运行
start();