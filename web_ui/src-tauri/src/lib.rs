/// DopaMatrix Tauri 应用核心入口
///
/// 生命周期策略：
///   1. 生产模式下通过 tauri-plugin-shell 启动 Python Sidecar（backend.exe）
///   2. 拦截 RunEvent::ExitRequested，在 Tauri 进程退出前执行两阶段后端清理：
///      Phase-1  HTTP POST /api/v1/system/shutdown  让 Python 自行优雅退出（纯 std TCP，无外部依赖）
///      Phase-2  taskkill /F /T /IM backend.exe     兜底斩杀整个进程树（Windows 专属）
///   这样无论 ProcessPoolExecutor 派生了多少子进程，都能被连根拔起。

use std::path::Path;
use std::process::Command;

#[tauri::command]
fn show_in_folder(path: String) -> Result<(), String> {
    let path_ref = Path::new(&path);
    if !path_ref.exists() {
        return Err(format!("Path does not exist: {path}"));
    }

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;

        // `explorer /select,"<path>"` 是 Windows 官方支持的"打开文件夹并高亮指定文件"方式，
        // 比 Shell.Application COM 自动化可靠得多：无需等待窗口出现、无需遍历窗口句柄。
        let select_arg = format!("/select,{}", path);
        let status = Command::new("explorer.exe")
            .creation_flags(CREATE_NO_WINDOW)
            .arg(&select_arg)
            .status()
            .map_err(|e| format!("Failed to launch explorer.exe /select: {e}"))?;

        // explorer.exe /select 在成功时返回 exit code 1（Windows 历史遗留行为），
        // 因此不能通过 status.success() 判断，只要能启动就视为成功。
        let _ = status;
    }

    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg("-R")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Failed to open finder: {e}"))?;
    }

    #[cfg(target_os = "linux")]
    {
        if let Some(dir) = path_ref.parent() {
            Command::new("xdg-open")
                .arg(dir)
                .spawn()
                .map_err(|e| format!("Failed to open file manager: {e}"))?;
        } else {
            return Err(format!("Path has no parent directory: {path}"));
        }
    }

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![show_in_folder])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // 生产环境下启动 Python FastAPI 后端 Sidecar；
            // 开发环境（debug_assertions）下跳过，避免与手动运行的 `python main.py` 冲突。
            if !cfg!(debug_assertions) {
                use tauri_plugin_shell::ShellExt;
                let sidecar_command = app
                    .shell()
                    .sidecar("backend")
                    .expect("failed to create `backend` binary command");
                let (mut rx, child) = sidecar_command
                    .spawn()
                    .expect("Failed to spawn sidecar");
                // 将 child 句柄移入 async 任务，通过持有所有权防止 Drop 提前触发进程回收。
                // rx 的持续消费确保 Tauri 内部管道不会因积压而阻塞 sidecar 输出。
                tauri::async_runtime::spawn(async move {
                    let _keep_alive = child;
                    while let Some(_event) = rx.recv().await {}
                });
            } else {
                println!("Running in dev mode: skipping sidecar spawn. Please start python backend manually.");
            }

            Ok(())
        })
        // 使用 build + run(closure) 模式以便挂载自定义事件处理器
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                // 仅在生产模式（Sidecar 实际运行）下执行后端清理
                #[cfg(not(debug_assertions))]
                shutdown_backend();
            }
        });
}

/// 两阶段后端关机：
///   Phase-1  向 Python 发送 HTTP 关机请求（纯 std::net::TcpStream，无 tokio/reqwest 依赖）
///   Phase-2  Windows taskkill 兜底，连根斩杀整个 backend.exe 进程树
#[cfg(not(debug_assertions))]
fn shutdown_backend() {
    const BACKEND_ADDR: &str = "127.0.0.1:8000";
    const SHUTDOWN_PATH: &str = "/api/v1/system/shutdown";
    const BACKEND_EXE: &str = "backend.exe";

    // ── Phase-1: 用原始 TCP 发送 HTTP POST，无需任何异步运行时 ──────
    let graceful_sent = send_http_shutdown(BACKEND_ADDR, SHUTDOWN_PATH);

    if graceful_sent {
        // 给 Python 留足时间执行 taskkill 自杀（Python 侧 0.5s 延迟 + 系统执行时间）
        std::thread::sleep(std::time::Duration::from_millis(1500));
    }

    // ── Phase-2: Windows 进程树兜底斩杀 ────────────────────────────
    // /F 强制  /T 包含全部子进程树  /IM 按名称匹配所有 backend.exe 实例
    // 即使 Phase-1 已成功，此处仍执行（taskkill 对不存在的进程静默返回 ERROR: 没有找到进程）
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;

        let _ = std::process::Command::new("taskkill")
            .args(["/F", "/T", "/IM", BACKEND_EXE])
            .creation_flags(CREATE_NO_WINDOW)
            .output();
    }
}

/// 用纯 std::net::TcpStream 发送 HTTP POST 关机请求。
///
/// 之所以不使用 reqwest::blocking：reqwest::blocking 内部会新建 tokio Runtime，
/// 若调用时已处于某个 tokio 上下文（Tauri 内部使用 tokio），会触发 panic。
/// 纯 TCP 方案完全规避该风险，同时无需添加任何额外依赖。
///
/// 返回 true 表示请求已成功发出并收到响应，false 表示后端不可达（已崩溃或未启动）。
#[cfg(not(debug_assertions))]
fn send_http_shutdown(addr: &str, path: &str) -> bool {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::time::Duration;

    let Ok(mut stream) = TcpStream::connect_timeout(
        &addr.parse().expect("invalid backend address"),
        Duration::from_secs(2),
    ) else {
        return false; // 后端不可达，直接跳到 Phase-2
    };

    stream.set_write_timeout(Some(Duration::from_secs(2))).ok();
    stream.set_read_timeout(Some(Duration::from_secs(3))).ok();

    let request = format!(
        "POST {path} HTTP/1.1\r\nHost: {addr}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    );

    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    // 读取响应首行，验证是否为 2xx
    let mut buf = [0u8; 64];
    match stream.read(&mut buf) {
        Ok(n) if n > 0 => {
            let resp = std::str::from_utf8(&buf[..n]).unwrap_or("");
            resp.starts_with("HTTP/1.1 2") || resp.starts_with("HTTP/1.0 2")
        }
        _ => false,
    }
}
