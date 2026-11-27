// GET /api/promo/config – is buying open (Stripe keys set) and is it the test mode
import { enabled, testMode, json, CPM_EUR, MIN_DAY_EUR, MIN_ORDER_EUR, SLOTS, VAT, MAKEGOOD } from "../../../lib/promo.js";
export const onRequestGet = ({ env }) => json({ enabled: enabled(env), test: testMode(env), cpm: CPM_EUR, min_day: MIN_DAY_EUR, min_order: MIN_ORDER_EUR, slots: SLOTS, vat: VAT, makegood: MAKEGOOD });
