// 백엔드 주소. 로컬에서 열면 로컬 서버, 배포 사이트에서는 Render 주소를 쓴다.
const PROD_API = "https://xiao-iot-api-2e6u.onrender.com";

const isLocal = ["localhost", "127.0.0.1", ""].includes(location.hostname);
window.API_BASE = isLocal ? "http://127.0.0.1:8000" : PROD_API;
