"""Trusted first-party agent packages. Never load untrusted executable code here."""
PACKAGES = {
 'website-chat': {'name': 'Website Chat', 'trigger': 'chat.message', 'description': 'Helpful answers, right on your website.', 'permissions': ['respond'], 'instructions': 'You are a concise website support assistant. Only use the supplied business guidance. If unsure, offer human support. Never claim to have accessed orders or taken actions.'},
 'email-support': {'name': 'Email Support', 'trigger': 'email.received', 'description': 'Thoughtful email drafts, ready for your review.', 'permissions': ['read_email', 'draft_email'], 'instructions': 'Draft a helpful support email using only the supplied business guidance. Do not send mail or claim actions were completed. Return only the draft.'}
}
