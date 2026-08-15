import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createApiModule } from "./fixtures.js";

const api = vi.hoisted(() => ({}));
vi.mock("../services/api.js", () => api);

import Agent from "../pages/Agent.jsx"; // eslint-disable-line import/first

beforeEach(() => {
  for (const key of Object.keys(api)) delete api[key];
  Object.assign(api, createApiModule(vi));
});

const agentResponse = (overrides) => ({
  answer:
    "Your household is forecast to use about 9,400 kWh in the next 7 days.",
  tools_used: ["get_household_overview"],
  data_points: [
    { label: "Average daily", value: 1330, unit: "kWh" },
    { label: "Next 7 days", value: 9321, unit: "kWh" },
  ],
  scope: "household",
  timestamp: "t",
  conversation_id: "conv-abc",
  model: "mock-router",
  mode: "mock",
  ...overrides,
});

const sendMessage = async (user, text) => {
  await user.type(screen.getByLabelText("Ask the AI Energy Assistant"), text);
  await user.click(screen.getByRole("button", { name: /send/i }));
};

describe("AI Energy Assistant page", () => {
  it("renders the heading, input and the conversational household suggestions", async () => {
    render(<Agent />);
    expect(screen.getByText("AI Energy Assistant")).toBeInTheDocument();
    expect(screen.getByLabelText("Ask the AI Energy Assistant")).toBeInTheDocument();
    expect(screen.getByText("What is my electricity bill?")).toBeInTheDocument();
    expect(screen.getByText("Will Diwali affect my electricity usage?")).toBeInTheDocument();
    expect(screen.getByText("What will my consumption look like next month?")).toBeInTheDocument();
    expect(screen.getByText("Is my consumption too high compared to normal?")).toBeInTheDocument();
    expect(screen.getByText("What is my current consumption right now?")).toBeInTheDocument();
    expect(screen.getByText("What if I use 250 kWh instead of 350?")).toBeInTheDocument();
  });

  it("sends a message and renders the grounded household answer with tools and data", async () => {
    api.chatWithAgent.mockResolvedValue(agentResponse());
    const user = userEvent.setup();
    render(<Agent />);

    await sendMessage(user, "What is my bill?");

    expect(api.chatWithAgent).toHaveBeenCalledWith("What is my bill?", null);
    expect(
      await screen.findByText("Your household is forecast to use about 9,400 kWh in the next 7 days.")
    ).toBeInTheDocument();
    expect(screen.getByText("Average daily")).toBeInTheDocument();
    expect(screen.getByText("1330 kWh")).toBeInTheDocument();
    expect(screen.getByText("household overview")).toBeInTheDocument();
    expect(screen.getByText("Household")).toBeInTheDocument();
  });

  it("sends the clicked suggestion verbatim", async () => {
    api.chatWithAgent.mockResolvedValue(agentResponse());
    const user = userEvent.setup();
    render(<Agent />);

    await user.click(screen.getByText("Will Diwali affect my electricity usage?"));

    expect(api.chatWithAgent).toHaveBeenCalledWith(
      "Will Diwali affect my electricity usage?",
      null
    );
    expect(await screen.findByText(/9,400 kWh/)).toBeInTheDocument();
  });

  it("keeps reusing the conversation id across a thread", async () => {
    api.chatWithAgent.mockResolvedValue(agentResponse());
    const user = userEvent.setup();
    render(<Agent />);

    await sendMessage(user, "What is my bill?");
    await user.type(screen.getByLabelText("Ask the AI Energy Assistant"), "What if I reduce it by 10%?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(api.chatWithAgent).toHaveBeenLastCalledWith("What if I reduce it by 10%?", "conv-abc");
  });

  it("shows a friendly error when the agent call fails", async () => {
    api.chatWithAgent.mockRejectedValueOnce(new Error("Agent not configured"));
    const user = userEvent.setup();
    render(<Agent />);

    await sendMessage(user, "status?");

    expect(await screen.findByText(/Agent not configured/i)).toBeInTheDocument();
  });

  it("clears the conversation and resets the conversation id", async () => {
    api.chatWithAgent.mockResolvedValue(agentResponse());
    const user = userEvent.setup();
    render(<Agent />);

    await sendMessage(user, "hello");
    expect(await screen.findByText(/9,400 kWh/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /clear conversation/i }));
    expect(screen.queryByText("hello")).not.toBeInTheDocument();

    await sendMessage(user, "again");
    expect(api.chatWithAgent).toHaveBeenLastCalledWith("again", null);
  });

  it("renders a greeting reply with no tools and no data cards", async () => {
    api.chatWithAgent.mockResolvedValue(
      agentResponse({ answer: "Hi! 👋 I'm your AI Energy Assistant. Ask away!", tools_used: [], data_points: [] })
    );
    const user = userEvent.setup();
    render(<Agent />);

    await sendMessage(user, "Hi!");

    expect(await screen.findByText("Hi! 👋 I'm your AI Energy Assistant. Ask away!")).toBeInTheDocument();
    expect(screen.queryByText("Tools used")).not.toBeInTheDocument();
    expect(screen.queryByText("Average daily")).not.toBeInTheDocument();
    expect(screen.getByText("Household")).toBeInTheDocument();
  });

  it("renders the festival outlook tool chip and its data point", async () => {
    api.chatWithAgent.mockResolvedValue(
      agentResponse({
        answer: "The household festival outlook starts with Diwali on 2026-11-08.",
        tools_used: ["get_festival_outlook"],
        data_points: [
          { label: "Next festival", value: "Diwali", unit: "" },
          { label: "Festival effect", value: "HIGHER_THAN_NORMAL", unit: "" },
        ],
      })
    );
    const user = userEvent.setup();
    render(<Agent />);

    await sendMessage(user, "Will Diwali affect my usage?");

    expect(await screen.findByText("festival outlook")).toBeInTheDocument();
    expect(screen.getByText("Diwali")).toBeInTheDocument();
    expect(screen.getByText("HIGHER_THAN_NORMAL")).toBeInTheDocument();
  });

  it("renders the current consumption tool chip and latest reading", async () => {
    api.chatWithAgent.mockResolvedValue(
      agentResponse({
        answer: "Your latest reading is 342.5 kWh at 2025-12-31 22:00:00.",
        tools_used: ["get_current_consumption"],
        data_points: [{ label: "Latest reading", value: 342.5, unit: "kWh" }],
      })
    );
    const user = userEvent.setup();
    render(<Agent />);

    await sendMessage(user, "What is my current consumption?");

    expect(await screen.findByText("current consumption")).toBeInTheDocument();
    expect(screen.getByText("342.5 kWh")).toBeInTheDocument();
  });

  it("renders the classification tool chip and status data point", async () => {
    api.chatWithAgent.mockResolvedValue(
      agentResponse({
        answer: "Your household usage is classified as MEDIUM.",
        tools_used: ["get_household_classification"],
        data_points: [
          { label: "Status", value: "MEDIUM", unit: "" },
          { label: "Forecast mean", value: 9013.61, unit: "kWh" },
        ],
      })
    );
    const user = userEvent.setup();
    render(<Agent />);

    await sendMessage(user, "Is my consumption high?");

    expect(await screen.findByText("household classification")).toBeInTheDocument();
    expect(screen.getByText("9013.61 kWh")).toBeInTheDocument();
  });

  it("labels the what-if custom kWh tool chip", async () => {
    api.chatWithAgent.mockResolvedValue(
      agentResponse({
        answer: "Changing your usage from 350 kWh to 250 kWh would bring your bill to ₹1,722.75.",
        tools_used: ["calculate_household_what_if"],
        data_points: [
          { label: "Original bill", value: 2021.25, unit: "INR" },
          { label: "New bill", value: 1722.75, unit: "INR" },
        ],
      })
    );
    const user = userEvent.setup();
    render(<Agent />);

    await sendMessage(user, "What if I use 250 kWh instead?");

    expect(await screen.findByText("calculate household what if")).toBeInTheDocument();
    expect(screen.getByText("1722.75 INR")).toBeInTheDocument();
  });

  it("shows the mock LLM badge in demo mode", async () => {
    api.chatWithAgent.mockResolvedValue(agentResponse());
    const user = userEvent.setup();
    render(<Agent />);

    await sendMessage(user, "overview");

    expect(await screen.findByText("mock LLM")).toBeInTheDocument();
  });
});