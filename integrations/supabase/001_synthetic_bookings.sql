-- Run only in the dedicated SoloAI test project. No real customer data.
CREATE TABLE IF NOT EXISTS public.soloai_test_bookings (
  booking_id text PRIMARY KEY,
  customer_id text NOT NULL,
  status text NOT NULL CHECK (status IN ('confirmed','cancelled','pending')),
  change_allowed boolean NOT NULL DEFAULT false
);
ALTER TABLE public.soloai_test_bookings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.soloai_test_bookings FROM anon, authenticated;
GRANT SELECT ON public.soloai_test_bookings TO service_role;
INSERT INTO public.soloai_test_bookings VALUES
  ('BK-1001','customer-alex','confirmed',true),
  ('BK-1002','customer-sam','cancelled',false),
  ('BK-1003','customer-alex','pending',false)
ON CONFLICT (booking_id) DO NOTHING;
-- Only this function's server credential may read the synthetic table.
-- No public Data API read policies are created.
