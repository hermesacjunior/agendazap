-- Foto de perfil do usuario, guardada como data URL (data:image/...;base64,...).
-- Redimensionada no cliente antes do upload; aparece na agenda publica.

alter table public.users
  add column if not exists avatar text;
