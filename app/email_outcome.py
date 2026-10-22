"""Operator-facing outcomes. Execution failures stay failures in metrics and audit."""
import time

REASONS = {
    'model_safety_blocked': ('Azure blocked this request under its safety policy.', 'Review the original email and write a safe reply. Do not retry the same blocked request.'),
    'foundry_rejected': ('Azure rejected the model request.', 'Check model access and configuration. You can write a reply manually.'),
    'foundry_timeout': ('The model did not respond in time.', 'Review the email. Regenerate only if another model request is appropriate.'),
    'execution_timeout': ('Processing exceeded its time limit.', 'Review the email and tool results before regenerating.'),
    'worker_interrupted': ('Processing stopped before a result was saved.', 'Review this case. The previous request may have consumed tokens; it was not replayed automatically.'),
    'token_allowance_exhausted': ('This workspace has reached its token allowance.', 'Write a reply manually or increase the allowance before regenerating.'),
    'agent_definition_mismatch': ('The saved task uses a different agent configuration.', 'Regenerate this case with the current configuration.'),
    'invalid_foundry_response': ('The model returned a response SoloAI could not validate.', 'Write a reply manually or regenerate after checking the request.'),
}


def outcome(row, delivery=None):
    expired=row['expires_at']<=int(time.time())
    status=delivery['status'] if delivery else row['status']
    if status=='SENT':
        return dict(outcome='SENT',review_required=False,reason='The email provider accepted the reply.',next_action='Acceptance does not confirm delivery to the recipient.')
    if status=='UNKNOWN':
        return dict(outcome='DELIVERY_UNCERTAIN',review_required=True,reason='The provider may have sent this reply, but confirmation was not saved.',next_action='Check the mailbox Sent folder before taking action. SoloAI will not resend it.')
    if status=='DISPATCHING':
        return dict(outcome='SENDING',review_required=False,reason='A send attempt is in progress.',next_action='Wait for confirmation. Do not send another copy.')
    if expired:
        return dict(outcome='EXPIRED',review_required=False,reason='The retained email content has expired.',next_action='Handle this case in the source mailbox.')
    if status=='FAILED':
        reason,action=REASONS.get(row.get('error'),('Processing could not finish safely.','Review the original email and write a reply, or investigate before regenerating.'))
        if delivery:reason,action='The email provider rejected the send attempt.','Check mailbox authorization and the draft before trying again.'
        return dict(outcome='NEEDS_REVIEW',review_required=True,reason=reason,next_action=action)
    if status in ('WAITING_FOR_REVIEW','APPROVED'):
        return dict(outcome='NEEDS_REVIEW',review_required=True,reason='A person must verify the facts before replying.' if row['needs_human'] else 'A draft is ready for review.',next_action='Review or edit the draft, then send when appropriate.')
    return dict(outcome={'QUEUED':'QUEUED','RUNNING':'PROCESSING','REJECTED':'CLOSED'}.get(status,status),review_required=False,reason='No reply has been sent.',next_action='Wait for processing.' if status in ('QUEUED','RUNNING') else 'No action is scheduled.')
