import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { Button, Card, ErrorText, H, T, styles } from "@/components/ui";
import { api, post, REPEAT_LABEL, type Schedule } from "@/lib/api";
import { confirmAsync } from "@/lib/confirm";

/** Reminders and repeating jobs set from chat, with a way to cancel them. */
export function Schedules() {
  const [items, setItems] = useState<Schedule[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Schedule[]>("/schedules")
      .then(setItems)
      .catch((e) => setError((e as Error).message));
  }, []);
  useFocusEffect(load);

  const cancel = async (s: Schedule) => {
    if (
      !(await confirmAsync(
        `Cancel "${s.title}"?`,
        "It will not run again.",
        "Cancel it",
        true,
      ))
    )
      return;
    try {
      await post(`/schedules/${s.id}/cancel`);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const [briefBusy, setBriefBusy] = useState(false);
  const setBriefing = async (time: string) => {
    setBriefBusy(true);
    setError(null);
    try {
      await post("/schedules/briefing", { time });
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBriefBusy(false);
    }
  };

  const active = (items ?? []).filter((s) => s.active);
  const briefing = active.find(
    (s) => s.kind === "task" && s.title === "Morning briefing",
  );
  const briefingAt = briefing?.next_run_at
    ? new Date(briefing.next_run_at).toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: briefing.timezone,
      })
    : null;
  return (
    <>
      <H>Reminders & repeating jobs</H>
      <Card>
        <T bold>☀️ Morning briefing</T>
        <T small muted>
          {briefingAt
            ? `On · every day at ${briefingAt}. Tap a time to change it.`
            : "Calendar, important mail, weather, news and today’s reminders, every day. Pick a time to turn it on."}
        </T>
        <View
          style={{
            flexDirection: "row",
            flexWrap: "wrap",
            gap: 8,
            marginTop: 8,
          }}
        >
          {["06:30", "07:00", "07:30", "08:00", "09:00"].map((t) => (
            <Pressable
              key={t}
              disabled={briefBusy}
              onPress={() => setBriefing(t)}
              accessibilityRole="button"
              accessibilityLabel={`Morning briefing at ${t}`}
              accessibilityState={{ selected: briefingAt === t }}
              style={{
                borderWidth: 1,
                borderColor: "#466a65",
                backgroundColor: briefingAt === t ? "#466a65" : "transparent",
                borderRadius: 999,
                paddingVertical: 6,
                paddingHorizontal: 14,
                opacity: briefBusy ? 0.5 : 1,
              }}
            >
              <Text
                style={{
                  color: briefingAt === t ? "#fff" : "#466a65",
                  fontWeight: "600",
                }}
              >
                {t}
              </Text>
            </Pressable>
          ))}
        </View>
      </Card>
      <ErrorText>{error}</ErrorText>
      {items && active.length === 0 && (
        <Card>
          <T small muted>
            None yet. Ask in chat: “remind me at 6pm to call mom” or “every
            Monday at 9 send me a summary of my unread email”.
          </T>
        </Card>
      )}
      {active.map((s) => (
        <Card key={s.id}>
          <View style={styles.between}>
            <View style={{ flex: 1 }}>
              <T bold>
                {s.kind === "reminder" ? "⏰ " : "🔁 "}
                {s.title}
              </T>
              <T small muted>
                {s.kind === "reminder" ? "Reminder" : "Job for your workforce"}{" "}
                · {REPEAT_LABEL[s.repeat]}
                {s.next_run_at
                  ? ` · next ${new Date(s.next_run_at).toLocaleString([], {
                      weekday: "short",
                      day: "numeric",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}`
                  : ""}
              </T>
            </View>
            <Button
              title="Cancel"
              small
              variant="ghost"
              onPress={() => cancel(s)}
            />
          </View>
        </Card>
      ))}
    </>
  );
}
