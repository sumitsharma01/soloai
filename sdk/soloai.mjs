/** Server-only SDK. Authenticate your end user before forwarding an event. */
export class SoloAI {
  constructor({baseUrl, apiKey}) {
    if (!baseUrl || !apiKey) throw new Error('SoloAI URL and key are required');
    this.baseUrl=baseUrl.replace(/\/$/,''); this.apiKey=apiKey;
  }
  async emit(type,{content}) {
    const response=await fetch(this.baseUrl+'/api/events',{
      method:'POST',signal:AbortSignal.timeout(60000),
      headers:{'Authorization':`Bearer ${this.apiKey}`,'Content-Type':'application/json'},
      body:JSON.stringify({type,content})
    });
    const result=await response.json();
    if(!response.ok) throw new Error(`SoloAI ${response.status}: ${result.detail}`);
    return result;
  }
}
