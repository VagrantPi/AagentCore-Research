// 反例：直接引用非必填欄位 reason，沒有先用 has 檢查。
// 在 AgentCore 上這種 policy 可能照樣 ACTIVE，但請求沒帶 reason 時整個評估出錯、回 403。
// 本機的 Cedar validator 可以在上線前就抓出來。
@id("bad-reason-length")
permit (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"OrderTarget___process_refund",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:gateway/demo"
) when {
  context.input.reason != ""
};
