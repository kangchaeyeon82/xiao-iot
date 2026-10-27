-- Supabase 대시보드 > SQL Editor 에 붙여넣고 Run

-- 센서 측정값 (ESP32가 2초마다 1행씩 추가)
create table if not exists public.sensor_readings (
  id          bigint generated always as identity primary key,
  device_id   text        not null,
  temperature real,
  rssi        integer,
  created_at  timestamptz not null default now()
);
create index if not exists sensor_readings_device_time
  on public.sensor_readings (device_id, created_at desc);

-- 장치 상태 (LED 목표 상태 + 마지막 접속 시각)
create table if not exists public.device_state (
  device_id  text primary key,
  led        boolean     not null default false,
  updated_at timestamptz not null default now(),
  last_seen  timestamptz
);
insert into public.device_state (device_id) values ('xiao-01')
  on conflict (device_id) do nothing;

-- RLS 켜고 정책은 만들지 않음 → 브라우저(anon 키)로는 직접 접근 불가,
-- 백엔드(service_role/secret 키)만 읽고 쓸 수 있음
alter table public.sensor_readings enable row level security;
alter table public.device_state    enable row level security;
