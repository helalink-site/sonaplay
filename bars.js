(function(){function col(){var m=document.querySelector('meta[name="theme-color"]'),c=m&&m.content;if(!c)c=getComputedStyle(document.documentElement).getPropertyValue('--v').trim();return c}
function send(){try{var c=col();if(c&&window.SonaNative&&SonaNative.setBars)SonaNative.setBars(c)}catch(e){}}
send();setTimeout(send,1500);var m=document.querySelector('meta[name="theme-color"]');if(m&&window.MutationObserver)new MutationObserver(send).observe(m,{attributes:true,attributeFilter:['content']});document.addEventListener('visibilitychange',send)})();
