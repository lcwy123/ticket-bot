/**
 * AutoJS WebSocket 最小测试
 */

let TAG = "WS_Test";
let ws = null;
let isConnected = false;

function log(msg) {
    console.log("[" + TAG + "] " + msg);
}

function connect() {
    let url = "ws://121.43.146.124:8000/api/agent/device/ws/test_phone";
    log("开始连接: " + url);

    try {
        ws = new WebSocket(url);
        log("WebSocket 对象创建成功");
    } catch (e) {
        log("创建 WebSocket 失败: " + e);
        return;
    }

    ws.onopen = function() {
        log("onopen 被调用！连接已建立");
        isConnected = true;

        let msg = {
            type: "register",
            device_id: "test_phone",
            device_name: "TestDevice"
        };
        log("发送: " + JSON.stringify(msg));
        ws.send(JSON.stringify(msg));
        log("send() 调用完成");
    };

    ws.onmessage = function(event) {
        log("收到消息: " + event.data);
    };

    ws.onerror = function(error) {
        log("onerror: " + JSON.stringify(error));
    };

    ws.onclose = function(event) {
        log("onclose - code: " + event.code + ", reason: " + event.reason);
        isConnected = false;
        // 5秒后重连
        log("5秒后重连...");
        setTimeout(connect, 5000);
    };
}

function main() {
    log("WebSocket 测试开始");
    connect();

    // 保持运行
    log("等待连接...");
}

main();