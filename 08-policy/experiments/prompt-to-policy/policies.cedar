// 規則 1：查詢訂單，所有已登入的使用者都可以
@id("allow-get-order")
permit (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"OrderTarget___get_order",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:gateway/demo"
);

// 規則 2：一般客服，單筆退款上限 500 美元，只限美加，而且一定要填退款原因
@id("allow-refund-agent")
permit (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"OrderTarget___process_refund",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:gateway/demo"
) when {
  context.input.amountCents <= 50000 &&
  ["US", "CA"].contains(context.input.country) &&
  context.input has reason
};

// 規則 3：主管，上限提高到 5,000 美元，其他條件不變
@id("allow-refund-supervisor")
permit (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"OrderTarget___process_refund",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:gateway/demo"
) when {
  principal.hasTag("role") && principal.getTag("role") == "supervisor" &&
  context.input.amountCents <= 500000 &&
  ["US", "CA"].contains(context.input.country) &&
  context.input has reason
};

// 規則 4：只能退自己的訂單（principal.id 就是 JWT 的 sub），主管例外
// forbid 優先於 permit：不管上面哪條 permit 成立，都會被這條擋下
@id("forbid-others-order")
forbid (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"OrderTarget___process_refund",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:gateway/demo"
) when {
  context.input.customerId != principal.id
} unless {
  principal.hasTag("role") && principal.getTag("role") == "supervisor"
};
