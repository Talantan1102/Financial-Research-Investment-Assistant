# 帧动图源 (frame-by-frame GIF sources)

每个 `*.html` 是一个自包含的逐帧示意图(iOS 简约风),用 `window.setFrame(n)` 切帧、
`window.FRAME_COUNT` 暴露帧数。再生 GIF 的流程:

1. 本地起 http 服务(file:// 被浏览器拦),如 `python -m http.server`。
2. headless 浏览器(deviceScaleFactor=3(2700px 物理像素,4K HiDPI 清晰))逐帧 `setFrame(i)` → 截 900×362(agent-flow)/900×506(sse) @2x → 1800px 物理像素 → 存 `frame-XX.png`。
3. PIL 拼成动态 WebP(无损,3x → 4K 清晰):`Image.save(out, format='WEBP', save_all=True, append_images=..., duration=[...], loop=0, lossless=True, method=6)`。
4. GIF 放 `dashboard/screenshots/{cap_id}/`,并加进该卡 `screenshots` 字段 → 渲染在卡片"图示 · Visuals"区。

当前产物:agent-flow.webp(lifecycle.langgraph_skeleton)、sse-stream.webp(lifecycle.sse_streaming)。
