// CDP transport to a specifically owned browser endpoint. Does not discover,
// attach to, authorize or launch an existing user browser.
export async function connectCdp({url,signal,timeoutMs=30000,WebSocketClass=globalThis.WebSocket}){
 signal?.throwIfAborted();
 const endpoint=new URL(url);
 if(endpoint.protocol!=='ws:'||endpoint.hostname!=='127.0.0.1'||!endpoint.port||endpoint.username||endpoint.password||endpoint.search||endpoint.hash||!/^\/devtools\/browser\/[A-Za-z0-9-]+$/.test(endpoint.pathname))throw Error('owned loopback browser endpoint required');
 if(!Number.isSafeInteger(timeoutMs)||timeoutMs<1||timeoutMs>60000||typeof WebSocketClass!=='function')throw Error('bounded CDP transport configuration');
 let sequence=0,closed=false,opened=false;
 const pending=new Map(),socket=new WebSocketClass(url);
 let acceptOpen,rejectOpen;
 const ready=new Promise((resolve,reject)=>{acceptOpen=resolve;rejectOpen=reject;});
 const startTimer=setTimeout(()=>stop(Error('CDP connection timeout')),timeoutMs);
 const rejectAll=error=>{for(const item of [...pending.values()])item.finish(false,error);};
 function stop(error=Error('CDP connection closed')){
  if(closed)return;closed=true;clearTimeout(startTimer);signal?.removeEventListener('abort',parentAbort);
  if(!opened)rejectOpen(error);rejectAll(error);
  try{socket.close();}catch{}
 }
 const parentAbort=()=>stop(signal.reason??Error('CDP connection cancelled'));
 signal?.addEventListener('abort',parentAbort,{once:true});
 socket.addEventListener('open',()=>{if(closed)return;opened=true;clearTimeout(startTimer);acceptOpen();});
 socket.addEventListener('error',()=>stop(Error('CDP socket error')));
 socket.addEventListener('close',()=>stop(Error('CDP connection closed')));
 socket.addEventListener('message',event=>{
  if(closed)return;
  let message;try{if(typeof event.data!=='string')throw Error('binary CDP response');message=JSON.parse(event.data);if(!message||Array.isArray(message)||typeof message!=='object')throw Error('invalid CDP envelope');}catch{stop(Error('invalid CDP message'));return;}
  if(message.id===undefined)return; // Events have no pending result to settle.
  const item=pending.get(message.id);if(!item)return; // Cancelled/timed-out reply.
  if((message.sessionId??null)!==item.sessionId){stop(Error('CDP response session mismatch'));return;}
  if(message.error)item.finish(false,Error(`CDP ${item.method}: ${message.error.message??'protocol error'}`));
  else if(message.result&&typeof message.result==='object')item.finish(true,message.result);
  else stop(Error('invalid CDP result'));
 });
 if(signal?.aborted)parentAbort();
 await ready;
 return Object.freeze({
  close:()=>stop(),
  async send(method,params={},options={}){
   if(closed)throw Error('CDP connection closed');signal?.throwIfAborted();options.signal?.throwIfAborted();
   if(typeof method!=='string'||!method.includes('.')||!params||typeof params!=='object')throw Error('explicit CDP method/parameters required');
   const sessionId=options.sessionId??null;
   if(sessionId!==null&&(typeof sessionId!=='string'||!sessionId))throw Error('CDP session identity');
   const id=++sequence;
   return await new Promise((resolve,reject)=>{
    let timer;
    const finish=(ok,value)=>{if(!pending.has(id))return;pending.delete(id);clearTimeout(timer);options.signal?.removeEventListener('abort',abort);(ok?resolve:reject)(value);};
    const abort=()=>finish(false,options.signal.reason??Error('CDP request cancelled'));
    pending.set(id,{sessionId,method,finish});
    options.signal?.addEventListener('abort',abort,{once:true});
    timer=setTimeout(()=>finish(false,Error(`CDP request timeout: ${method}`)),timeoutMs);
    try{socket.send(JSON.stringify({id,method,params,...(sessionId===null?{}:{sessionId})}));}catch(error){stop(error);}
   });
  }
 });
}
