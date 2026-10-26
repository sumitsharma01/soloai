/* Stream mono PCM16 at the AudioContext's 24 kHz rate. Never store recordings. */
class VoiceCapture extends AudioWorkletProcessor {
  constructor(){super();this.pending=[];}
  process(inputs){
    const input=inputs[0]?.[0];
    if(input){for(const value of input)this.pending.push(Math.round(Math.max(-1,Math.min(1,value))*32767));
      if(this.pending.length>=2400){const pcm=new Int16Array(this.pending);this.port.postMessage(pcm.buffer,[pcm.buffer]);this.pending=[];}}
    return true;
  }
}
registerProcessor('voice-capture',VoiceCapture);
