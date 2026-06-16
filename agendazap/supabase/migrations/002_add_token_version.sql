-- token_version: incrementado ao trocar a senha. Vai embutido no JWT como
-- "ver"; ao incrementar, invalida todas as sessoes ativas (logout global) e
-- torna o token de recuperacao de senha de uso unico.

alter table public.users
  add column if not exists token_version integer not null default 0;
