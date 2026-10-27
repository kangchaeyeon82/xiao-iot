// 백엔드 주소. 로컬에서 열면 로컬 서버, 배포 사이트에서는 Render 주소를 쓴다.
// 3단계(배포)에서 PROD_API 를 Render URL로 바꾼다.
const PROD_API = "https://REPLACE-ME.onrender.com";

const isLocal = ["localhost", "127.0.0.1", ""].includes(location.hostname);
window.API_BASE = isLocal ? "http://127.0.0.1:8000" : PROD_API;
