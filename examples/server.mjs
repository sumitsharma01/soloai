import { SoloAI } from '../sdk/soloai.mjs';
const solo = new SoloAI({baseUrl:process.env.SOLOAI_URL,apiKey:process.env.SOLOAI_API_KEY});
// In your real server: authenticate the caller and enforce per-user rate limits first.
console.log(await solo.emit('chat.message',{content:'What is your return policy?'}));
console.log(await solo.emit('email.received',{content:'Hi, can I return my order?'}));
// Email output is a draft. Show it to a human. Do not automatically send it.
