-- Schema de banco — Supabase (PostgreSQL)

create table if not exists public.users (
  id uuid primary key default auth.uid(),
  email text unique not null,
  created_at timestamp with time zone default now()
);

create table if not exists public.categories (
  id bigserial primary key,
  user_id uuid not null,
  name text not null,
  constraint fk_cat_user foreign key (user_id) references public.users(id)
);

create table if not exists public.expenses (
  id bigserial primary key,
  user_id uuid not null,
  dt date not null,
  category_id bigint,
  description text,
  amount numeric(12,2) not null check (amount >= 0),
  created_at timestamp with time zone default now(),
  constraint fk_exp_user foreign key (user_id) references public.users(id),
  constraint fk_exp_cat foreign key (category_id) references public.categories(id)
);

-- Habilitar RLS
alter table public.users enable row level security;
alter table public.categories enable row level security;
alter table public.expenses enable row level security;

-- Políticas básicas
create policy users_select_self on public.users for select using (id = auth.uid());

create policy categories_rw_own on public.categories
for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy expenses_rw_own on public.expenses
for all using (user_id = auth.uid()) with check (user_id = auth.uid());
