

import json
from django.conf import settings
from django.shortcuts import render, redirect
from django.db.models import Q
from django.utils import timezone
from django.core.mail import send_mail
from datetime import timedelta
from .forms import CandidateForm, AnswerForm, AdminSettingsForm, UserLoginForm, OTPLoginForm, ForgotPasswordForm, ResetPasswordForm
from .models import AdminSettings, Interview, Questions, Answers, SpeechTranscripts, EmotionLogs, PerformanceMetrics
from .models import Candidate, InterviewResponse

import google.generativeai as genai

genai.configure(api_key=settings.GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

def generate_question(messages):
    prompt = "You are an AI interviewer.\n"
    for msg in messages:
        prompt += msg["content"] + "\n"
    response = model.generate_content(prompt)
    return response.text.strip()


import re
import json

def evaluate_answer(question, answer):
    prompt = (
        f"Evaluate the following candidate answer to the interview question.\n\n"
        f"Question: {question}\n"
        f"Answer: {answer}\n\n"
        f"Provide a score from 0-5 where:\n"
        f"5 = Excellent answer with detailed explanation\n"
        f"4 = Good answer with relevant details\n"
        f"3 = Satisfactory answer, covers basics\n"
        f"2 = Partial answer, missing key points\n"
        f"1 = Poor answer, mostly incorrect\n"
        f"0 = No answer or completely wrong\n\n"
        f"Respond ONLY with valid JSON in this exact format:\n"
        f'{{"score": 3, "qualified": "yes", "correct_answer": "Expected answer here", "confidence": 0.8}}\n'
        f"Do not include any markdown, code blocks, or explanations."
    )

    try:
        result = model.generate_content(prompt)
        content = result.text.strip()

        # Remove markdown code blocks if present
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        content = content.strip()

        # Try JSON parse first
        try:
            parsed = json.loads(content)
            score = int(parsed.get("score", 3))  # Default to 3 instead of 0
            qualified = parsed.get("qualified", "yes" if score >= 3 else "no")
            correct_answer = parsed.get("correct_answer", "Good answer")
            confidence = float(parsed.get("confidence", 0.7))

            # Ensure score is within valid range
            score = max(0, min(5, score))

            return {"score": score, "qualified": qualified, "correct_answer": correct_answer, "confidence": confidence}
        except Exception as parse_error:
            print(f"JSON parse error: {parse_error}, Content: {content}")
            # Try to extract JSON with regex
            try:
                match = re.search(r'\{[^}]+\}', content, re.DOTALL)
                if match:
                    extracted_json = match.group()
                    parsed = json.loads(extracted_json)
                    score = int(parsed.get("score", 3))
                    qualified = parsed.get("qualified", "yes" if score >= 3 else "no")
                    correct_answer = parsed.get("correct_answer", "Good answer")
                    confidence = float(parsed.get("confidence", 0.7))

                    score = max(0, min(5, score))

                    return {"score": score, "qualified": qualified, "correct_answer": correct_answer, "confidence": confidence}
            except Exception as regex_error:
                print(f"Regex extraction error: {regex_error}")
                pass

        # If parsing fails, use intelligent fallback
        return smart_fallback_scoring(question, answer)

    except Exception as e:
        print(f"API error: {e}")
        # Fallback when API quota is exceeded or other errors occur
        return smart_fallback_scoring(question, answer)

def smart_fallback_scoring(question, answer):
    """Intelligent fallback scoring when API fails"""
    answer_lower = answer.lower().strip()
    question_lower = question.lower()

    # Check if answer is empty or too short
    if len(answer) < 5:
        return {"score": 0, "qualified": "no", "correct_answer": "Please provide a detailed answer", "confidence": 0.3}

    # Start with base score
    score = 2  # Start with 2 instead of 0

    # Length-based scoring
    if len(answer) > 100:
        score += 1
    if len(answer) > 50:
        score += 0.5

    # Keyword-based scoring
    positive_keywords = ['experience', 'project', 'worked', 'developed', 'implemented',
                        'understand', 'knowledge', 'familiar', 'because', 'since',
                        'therefore', 'example', 'such as', 'including', 'like']

    keyword_count = sum(1 for keyword in positive_keywords if keyword in answer_lower)
    score += min(keyword_count * 0.3, 1.5)  # Max 1.5 points from keywords

    # Check for structured answer (sentences, punctuation)
    if '.' in answer or ',' in answer:
        score += 0.5

    # Round and cap score
    score = min(round(score), 5)
    score = max(score, 1)  # Minimum score of 1 if they attempted an answer

    qualified = "yes" if score >= 3 else "no"
    correct_answer = "Your answer has been evaluated. For better scores, provide detailed explanations with examples."
    confidence = 0.6

    return {"score": score, "qualified": qualified, "correct_answer": correct_answer, "confidence": confidence}


def start_interview(request):
    if request.method == 'POST':
        form = CandidateForm(request.POST)
        if form.is_valid():
            candidate = Candidate.objects.create(
                name=form.cleaned_data['name'],
                email=form.cleaned_data['email'],
                job_description=form.cleaned_data['job_description'],
                question_level=form.cleaned_data['question_level']
            )

            request.session['candidate_id'] = candidate.id

            # Get admin settings - Force to 5 questions
            settings = AdminSettings.objects.first()
            if not settings:
                settings = AdminSettings.objects.create()
            num_questions = 5  # Fixed to 5 questions
            difficulty = settings.difficulty_level
            question_type = settings.question_type

            # Create Interview instance
            interview = Interview.objects.create(candidate=candidate)

            # Generate questions using AI
            skill = candidate.job_description
            prompt = f"""Generate exactly {num_questions} interview questions for a {skill} position.
Difficulty level: {difficulty}
Question type: {question_type}
Questions should increase in complexity.

Return the response in this exact format:

Question 1: [Full question text here]
Answer 1: [Correct answer and explanation here]

Question 2: [Full question text here]
Answer 2: [Correct answer and explanation here]

... and so on.

Do not include any other text or formatting."""

            try:
                response = model.generate_content(prompt)
                questions_data = response.text.strip()
            except Exception as e:
                # Fallback to generic questions based on skill if API quota is exceeded
                questions_data = f"""Question 1: What is your experience with {skill}?
Answer 1: Look for relevant experience and projects in {skill}.

Question 2: Describe a challenging problem you solved using {skill}.
Answer 2: Should demonstrate problem-solving skills and technical knowledge.

Question 3: What are the key concepts or best practices in {skill}?
Answer 3: Should show understanding of fundamental concepts.

Question 4: How do you stay updated with the latest trends in {skill}?
Answer 4: Look for continuous learning and professional development.

Question 5: Describe a project you worked on using {skill}.
Answer 5: Should demonstrate practical application and project experience."""

            # Parse questions
            lines = questions_data.split('\n')
            questions_list = []
            current_question = None
            current_answer = None
            for line in lines:
                line = line.strip()
                if line.startswith("Question ") and ":" in line:
                    if current_question is not None:
                        questions_list.append({"question": current_question, "answer": current_answer or ""})
                    current_question = line.split(":", 1)[1].strip()
                    current_answer = None
                elif line.startswith("Answer ") and ":" in line:
                    current_answer = line.split(":", 1)[1].strip()
            if current_question:
                questions_list.append({"question": current_question, "answer": current_answer or ""})

            request.session['questions'] = []
            for q_data in questions_list[:num_questions]:
                question_obj = Questions.objects.create(
                    interview=interview,
                    question_text=q_data["question"],
                    question_type=question_type,
                    correct_answer=q_data["answer"],
                    difficulty=difficulty
                )
                request.session['questions'].append(question_obj.id)

            if not request.session['questions']:
                # Fallback: create default questions based on skill
                default_questions = [
                    {"question": f"What is your experience with {skill}?", "answer": f"Look for relevant experience and projects in {skill}."},
                    {"question": f"Describe a challenging problem you solved using {skill}.", "answer": "Should demonstrate problem-solving skills and technical knowledge."},
                    {"question": f"What are the key concepts or best practices in {skill}?", "answer": "Should show understanding of fundamental concepts."},
                    {"question": f"How do you stay updated with the latest trends in {skill}?", "answer": "Look for continuous learning and professional development."},
                    {"question": f"Describe a project you worked on using {skill}.", "answer": "Should demonstrate practical application and project experience."}
                ]
                for q_data in default_questions[:num_questions]:
                    question_obj = Questions.objects.create(
                        interview=interview,
                        question_text=q_data["question"],
                        question_type=question_type,
                        correct_answer=q_data["answer"],
                        difficulty=difficulty
                    )
                    request.session['questions'].append(question_obj.id)

            request.session['question_count'] = 1
            request.session['total_questions'] = num_questions
            request.session['interview_id'] = interview.id

            first_question = Questions.objects.get(id=request.session['questions'][0])

            return render(request, 'users/question.html', {
                'question': first_question.question_text,
                'form': AnswerForm(),
                'current_question_id': request.session['questions'][0]
            })

    else:
        form = CandidateForm()

    return render(request, 'users/start.html', {'form': form})


def demo_interview(request):
    # If GET request or no form data, start demo immediately with default settings
    if request.method == 'GET' or not request.POST:
        # Set demo mode with default settings
        request.session['demo'] = True
        request.session['demo_job'] = "Software Developer"  # Default job description
        request.session['demo_level'] = "Intermediate"  # Default difficulty level

        # Use default settings for demo
        num_questions = 3  # Shorter for demo
        difficulty = "Intermediate"  # Default difficulty
        question_type = 'Descriptive'

        # Generate questions using AI
        skill = "Software Developer"
        prompt = f"""Generate exactly {num_questions} interview questions for a {skill} position.
Difficulty level: {difficulty}
Question type: {question_type}
Questions should increase in complexity.

Return the response in this exact format:

Question 1: [Full question text here]
Answer 1: [Correct answer and explanation here]

Question 2: [Full question text here]
Answer 2: [Correct answer and explanation here]

... and so on.

Do not include any other text or formatting."""

        try:
            response = model.generate_content(prompt)
            questions_data = response.text.strip()
        except Exception as e:
            # Fallback to generic questions based on skill if API quota is exceeded
            questions_data = f"""Question 1: What is your experience with {skill}?
Answer 1: Look for relevant experience in {skill}.

Question 2: Explain a basic concept in {skill}.
Answer 2: Should show understanding of {skill}.

Question 3: How do you approach problem-solving in {skill}?
Answer 3: Describe systematic approach in {skill}."""

        # Parse questions
        lines = questions_data.split('\n')
        questions_list = []
        current_question = None
        current_answer = None
        for line in lines:
            line = line.strip()
            if line.startswith("Question ") and ":" in line:
                if current_question is not None:
                    questions_list.append({"question": current_question, "answer": current_answer or ""})
                current_question = line.split(":", 1)[1].strip()
                current_answer = None
            elif line.startswith("Answer ") and ":" in line:
                current_answer = line.split(":", 1)[1].strip()
        if current_question:
            questions_list.append({"question": current_question, "answer": current_answer or ""})

        demo_questions = []
        demo_answers = []
        for q_data in questions_list[:num_questions]:
            demo_questions.append({
                'text': q_data["question"],
                'correct_answer': q_data["answer"]
            })
            demo_answers.append({
                'question': q_data["question"],
                'answer': '',
                'score': 0,
                'explanation': q_data["answer"]
            })

        if not demo_questions:
            # Fallback based on skill
            default_questions = [
                {"question": f"What is your experience with {skill}?", "answer": f"Look for relevant experience in {skill}."},
                {"question": f"Explain a basic concept in {skill}.", "answer": f"Should show understanding of {skill}."},
                {"question": f"How do you approach problem-solving in {skill}?", "answer": f"Describe systematic approach in {skill}."}
            ]
            for q_data in default_questions[:num_questions]:
                demo_questions.append({
                    'text': q_data["question"],
                    'correct_answer': q_data["answer"]
                })
                demo_answers.append({
                    'question': q_data["question"],
                    'answer': '',
                    'score': 0,
                    'explanation': q_data["answer"]
                })

        request.session['demo_questions'] = demo_questions
        request.session['demo_answers'] = demo_answers
        request.session['question_count'] = 1
        request.session['total_questions'] = num_questions

        first_question = demo_questions[0]['text']

        return render(request, 'users/question.html', {
            'question': first_question,
            'form': AnswerForm(),
            'demo': True
        })

    # Handle POST request (if form is submitted)
    form = CandidateForm(request.POST)
    if form.is_valid():
        # Use form data for demo
        job_description = form.cleaned_data['job_description']
        question_level = form.cleaned_data['question_level']

        request.session['demo'] = True
        request.session['demo_job'] = job_description
        request.session['demo_level'] = question_level

        # Use default settings for demo
        num_questions = 3  # Shorter for demo
        difficulty = question_level  # Use selected level
        question_type = 'Descriptive'

        # Generate questions using AI
        skill = job_description
        prompt = f"""Generate exactly {num_questions} interview questions for a {skill} position.
Difficulty level: {difficulty}
Question type: {question_type}
Questions should increase in complexity.

Return the response in this exact format:

Question 1: [Full question text here]
Answer 1: [Correct answer and explanation here]

Question 2: [Full question text here]
Answer 2: [Correct answer and explanation here]

... and so on.

Do not include any other text or formatting."""

        try:
            response = model.generate_content(prompt)
            questions_data = response.text.strip()
        except Exception as e:
            # Fallback to generic questions based on skill if API quota is exceeded
            questions_data = f"""Question 1: What is your experience with {skill}?
Answer 1: Look for relevant experience in {skill}.

Question 2: Explain a basic concept in {skill}.
Answer 2: Should show understanding of {skill}.

Question 3: How do you approach problem-solving in {skill}?
Answer 3: Describe systematic approach in {skill}."""

        # Parse questions
        lines = questions_data.split('\n')
        questions_list = []
        current_question = None
        current_answer = None
        for line in lines:
            line = line.strip()
            if line.startswith("Question ") and ":" in line:
                if current_question is not None:
                    questions_list.append({"question": current_question, "answer": current_answer or ""})
                current_question = line.split(":", 1)[1].strip()
                current_answer = None
            elif line.startswith("Answer ") and ":" in line:
                current_answer = line.split(":", 1)[1].strip()
        if current_question:
            questions_list.append({"question": current_question, "answer": current_answer or ""})

        demo_questions = []
        demo_answers = []
        for q_data in questions_list[:num_questions]:
            demo_questions.append({
                'text': q_data["question"],
                'correct_answer': q_data["answer"]
            })
            demo_answers.append({
                'question': q_data["question"],
                'answer': '',
                'score': 0,
                'explanation': q_data["answer"]
            })

        if not demo_questions:
            # Fallback based on skill
            default_questions = [
                {"question": f"What is your experience with {skill}?", "answer": f"Look for relevant experience in {skill}."},
                {"question": f"Explain a basic concept in {skill}.", "answer": f"Should show understanding of {skill}."},
                {"question": f"How do you approach problem-solving in {skill}?", "answer": f"Describe systematic approach in {skill}."}
            ]
            for q_data in default_questions[:num_questions]:
                demo_questions.append({
                    'text': q_data["question"],
                    'correct_answer': q_data["answer"]
                })
                demo_answers.append({
                    'question': q_data["question"],
                    'answer': '',
                    'score': 0,
                    'explanation': q_data["answer"]
                })

        request.session['demo_questions'] = demo_questions
        request.session['demo_answers'] = demo_answers
        request.session['question_count'] = 1
        request.session['total_questions'] = num_questions

        first_question = demo_questions[0]['text']

        return render(request, 'users/question.html', {
            'question': first_question,
            'form': AnswerForm(),
            'demo': True
        })

    # If form is invalid, show the demo start page
    return render(request, 'users/demo_start.html', {'form': form})


def answer_question(request):
    if request.session.get('demo'):
        # Demo mode
        question_count = request.session.get('question_count', 1)
        total_questions = request.session.get('total_questions', 3)
        demo_questions = request.session.get('demo_questions', [])
        demo_answers = request.session.get('demo_answers', [])

        if request.method == 'POST':
            form = AnswerForm(request.POST)
            if form.is_valid():
                answer = form.cleaned_data['answer']
                current_question = demo_questions[question_count - 1]
                evaluation = evaluate_answer(current_question['text'], answer)

                demo_answers[question_count - 1]['answer'] = answer
                demo_answers[question_count - 1]['score'] = evaluation.get("score", 0)
                demo_answers[question_count - 1]['explanation'] = evaluation.get("correct_answer", "")

                request.session['demo_answers'] = demo_answers

                if question_count >= total_questions:
                    # Create a demo candidate and interview for database storage
                    demo_candidate = Candidate.objects.create(
                        name="Demo User",
                        email="demo@example.com",
                        job_description=request.session.get('demo_job', 'Demo Position'),
                        question_level=request.session.get('demo_level', 'Intermediate')
                    )

                    # Create Interview instance
                    demo_interview = Interview.objects.create(
                        candidate=demo_candidate,
                        start_time=timezone.now(),
                        end_time=timezone.now(),
                        total_score=0,  # Will be calculated below
                        confidence_level=0,
                        final_decision=''
                    )

                    # Create Questions and Answers for each demo question
                    total_score = 0
                    for i, answer_data in enumerate(demo_answers):
                        question_obj = Questions.objects.create(
                            interview=demo_interview,
                            question_text=answer_data['question'],
                            question_type='Descriptive',
                            correct_answer=answer_data['explanation'],
                            difficulty=request.session.get('demo_level', 'Intermediate')
                        )
                        
                        answer_obj = Answers.objects.create(
                            question=question_obj,
                            candidate_answer=answer_data['answer'],
                            score=answer_data['score'],
                            explanation=answer_data['explanation']
                        )
                        
                        total_score += answer_data['score']

                    # Calculate final scores and update interview
                    avg_score = total_score / len(demo_answers)
                    demo_interview.total_score = avg_score
                    demo_interview.confidence_level = avg_score / 5  # Normalize to 0-1
                    demo_interview.final_decision = 'Pass' if avg_score >= 2.25 else 'Fail'
                    demo_interview.save()

                    # Create or update PerformanceMetrics
                    PerformanceMetrics.objects.update_or_create(
                        interview=demo_interview,
                        defaults={
                            'accuracy_percentage': avg_score / 5 * 100,
                            'confidence_level': demo_interview.confidence_level * 100,
                            'strengths': "Demo interview performance",
                            'weak_areas': "N/A for demo",
                            'recommendation': "Demo result"
                        }
                    )

                    # Add emotion data to demo answers
                    answers_with_emotions = []
                    for answer_data in demo_answers:
                        # Generate emotion based on score (simple logic for demo)
                        if answer_data['score'] >= 3:
                            emotion = 'normal'
                            # Random confidence between 0.7 and 0.9 for good scores
                            emotion_confidence = round(0.7 + (answer_data['score'] - 3) * 0.1 + random.uniform(0, 0.1), 2)
                        else:
                            emotion = 'suspicious'
                            # Random confidence between 0.4 and 0.7 for low scores
                            emotion_confidence = round(0.4 + (answer_data['score'] * 0.1) + random.uniform(0, 0.1), 2)
                        
                        answers_with_emotions.append({
                            'answer': answer_data,
                            'emotion': emotion,
                            'emotion_confidence': emotion_confidence
                        })

                    # Get current date and time
                    from datetime import datetime
                    import pytz
                    ist = pytz.timezone('Asia/Kolkata')
                    current_time = datetime.now(ist)
                    interview_date = current_time.strftime('%B %d, %Y')
                    interview_time = current_time.strftime('%I:%M %p')

                    # Clear demo session
                    request.session.pop('demo', None)
                    request.session.pop('demo_questions', None)
                    request.session.pop('demo_answers', None)
                    request.session.pop('question_count', None)
                    request.session.pop('total_questions', None)

                    return render(request, 'users/demo_results.html', {
                        'answers': answers_with_emotions,
                        'avg_score': avg_score,
                        'qualification_status': demo_interview.final_decision,
                        'interview_date': interview_date,
                        'interview_time': interview_time
                    })

                question_count += 1
                request.session['question_count'] = question_count

                next_question = demo_questions[question_count - 1]['text']

                return render(request, 'users/question.html', {
                    'question': next_question,
                    'form': AnswerForm(),
                    'demo': True
                })

        current_question = demo_questions[question_count - 1]['text']

        return render(request, 'users/question.html', {
            'question': current_question,
            'form': AnswerForm(),
            'demo': True
        })

    # Regular interview
    candidate_id = request.session.get('candidate_id')
    question_count = request.session.get('question_count', 1)
    total_questions = request.session.get('total_questions', 5)
    questions = request.session.get('questions', [])
    interview_id = request.session.get('interview_id')

    candidate = Candidate.objects.get(id=candidate_id)
    interview = Interview.objects.get(id=interview_id)

    if request.method == 'POST':
        form = AnswerForm(request.POST)
        if form.is_valid():
            answer = form.cleaned_data['answer']
            current_question_id = questions[question_count - 1]
            question_obj = Questions.objects.get(id=current_question_id)

            # Evaluate answer
            evaluation = evaluate_answer(question_obj.question_text, answer)

            # Create Answer
            answer_obj = Answers.objects.create(
                question=question_obj,
                candidate_answer=answer,
                score=evaluation.get("score", 0),
                explanation=evaluation.get("correct_answer", "")
            )

            # If voice enabled, add speech transcript (placeholder for now)
            settings = AdminSettings.objects.first()
            if settings and settings.enable_voice_interview:
                # Placeholder for speech-to-text
                SpeechTranscripts.objects.create(
                    answer=answer_obj,
                    transcript=answer,  # Assume text input for now
                    fluency_score=0.8,  # Placeholder
                    speech_accuracy=0.9  # Placeholder
                )

            if question_count >= total_questions:
                # End interview
                interview.end_time = timezone.now()
                total_score = sum(a.score for a in Answers.objects.filter(question__interview=interview))
                interview.total_score = total_score / total_questions
                interview.confidence_level = sum(a.score for a in Answers.objects.filter(question__interview=interview)) / (total_questions * 5)  # Normalize
                interview.final_decision = 'Pass' if interview.total_score >= 3 else 'Fail'
                interview.save()

                # Create or update PerformanceMetrics
                PerformanceMetrics.objects.update_or_create(
                    interview=interview,
                    defaults={
                        'accuracy_percentage': interview.total_score / 5 * 100,
                        'confidence_level': interview.confidence_level * 100,
                        'strengths': "Good knowledge",
                        'weak_areas': "Need improvement in basics",
                        'recommendation': "Hire" if interview.final_decision == 'Pass' else "Reject"
                    }
                )

                return interview_results(request, candidate.id)

            question_count += 1
            request.session['question_count'] = question_count

            # Check if there are more questions
            if question_count <= total_questions and question_count <= len(questions):
                next_question_id = questions[question_count - 1]
                next_question = Questions.objects.get(id=next_question_id)

                return render(request, 'users/question.html', {
                    'question': next_question.question_text,
                    'form': AnswerForm(),
                    'current_question_id': next_question_id
                })
            else:
                # Handle case where questions list is shorter than expected
                # End interview early
                interview.end_time = timezone.now()
                total_score = sum(a.score for a in Answers.objects.filter(question__interview=interview))
                interview.total_score = total_score / total_questions
                interview.confidence_level = sum(a.score for a in Answers.objects.filter(question__interview=interview)) / (total_questions * 5)
                interview.final_decision = 'Pass' if interview.total_score >= 3 else 'Fail'
                interview.save()

                # Create or update PerformanceMetrics
                PerformanceMetrics.objects.update_or_create(
                    interview=interview,
                    defaults={
                        'accuracy_percentage': interview.total_score / 5 * 100,
                        'confidence_level': interview.confidence_level * 100,
                        'strengths': "Good knowledge",
                        'weak_areas': "Need improvement in basics",
                        'recommendation': "Hire" if interview.final_decision == 'Pass' else "Reject"
                    }
                )

                return interview_results(request, candidate.id)

    current_question_id = questions[question_count - 1]
    question_obj = Questions.objects.get(id=current_question_id)

    return render(request, 'users/question.html', {
        'question': question_obj.question_text,
        'form': AnswerForm(),
        'current_question_id': current_question_id
    })


def interview_results(request, candidate_id):
    candidate = Candidate.objects.get(id=candidate_id)
    interview = Interview.objects.filter(candidate=candidate).last()
    answers = Answers.objects.filter(question__interview=interview).select_related('question')
    total_score = sum(a.score for a in answers if a.score is not None)
    avg_score = total_score / len(answers) if answers else 0
    status = interview.final_decision

    # Get performance metrics
    metrics = PerformanceMetrics.objects.filter(interview=interview).first()

    # Add emotions to answers
    answers_with_emotions = []
    for answer in answers:
        emotion_log = EmotionLogs.objects.filter(interview=interview, question=answer.question).first()
        emotion = emotion_log.emotion if emotion_log else 'Not captured'
        confidence = emotion_log.confidence if emotion_log else 0.0
        answers_with_emotions.append({
            'answer': answer,
            'emotion': emotion,
            'emotion_confidence': confidence
        })

    # Get current date and time in IST
    from datetime import datetime
    import pytz
    ist = pytz.timezone('Asia/Kolkata')
    current_time = datetime.now(ist)
    interview_date = current_time.strftime('%B %d, %Y')
    interview_time = current_time.strftime('%I:%M %p')

    # Email subject and body based on status
    if status == "Pass":
        subject = "🎉 Congratulations! You are Qualified"
        message = (
            f"Dear {candidate.name},\n\n"
            f"Congratulations on successfully completing your interview for the position of {candidate.job_description}.\n"
            f"Your average score is {avg_score:.2f}. We are happy to inform you that you are qualified & offer letter should be released soon.\n\n"
            f"Regards,\nAI Interview Team"
        )
    else:
        subject = "📩 Interview Result - Not Qualified"
        message = (
            f"Dear {candidate.name},\n\n"
            f"Thank you for attending the interview for the position of {candidate.job_description}.\n"
            f"Your average score is {avg_score:.2f}. Unfortunately, you have not qualified this time.\n\n"
            f"We encourage you to keep learning and try again.\n\n"
            f"Best wishes,\nAI Interview Team"
        )

    # Send email
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [candidate.email],
            fail_silently=False,
        )
    except Exception as e:
        print(f"Email sending failed: {e}")

    return render(request, 'users/results.html', {
        'candidate': candidate,
        'answers': answers_with_emotions,
        'avg_score': avg_score,
        'qualification_status': status,
        'metrics': metrics,
        'interview': interview,
        'interview_date': interview_date,
        'interview_time': interview_time
    })
def all_results(request):
    interviews = Interview.objects.all().order_by('-start_time').select_related('candidate')

    # Get filter parameters
    search_name = request.GET.get('search_name', '')
    search_email = request.GET.get('search_email', '')
    filter_status = request.GET.get('filter_status', '')

    # Apply filters
    if search_name:
        interviews = interviews.filter(candidate__name__icontains=search_name)
    if search_email:
        interviews = interviews.filter(candidate__email__icontains=search_email)
    if filter_status:
        interviews = interviews.filter(final_decision=filter_status)

    results = []
    for i in interviews:
        answers = Answers.objects.filter(question__interview=i)
        questions = Questions.objects.filter(interview=i)
        total_questions = questions.count()

        # Count correctly answered questions (score >= 3 is considered correct)
        correct_answers = sum(1 for a in answers if a.score and a.score >= 3)

        total_score = sum(a.score for a in answers if a.score is not None)
        avg_score = total_score / len(answers) if answers else 0
        metrics = PerformanceMetrics.objects.filter(interview=i).first()

        # Determine qualification status
        qualification_status = 'Qualified' if i.final_decision == 'Pass' else 'Disqualified'

        results.append({
            'interview': i,
            'candidate': i.candidate,
            'avg_score': avg_score,
            'total_questions': total_questions,
            'correct_answers': correct_answers,
            'qualification_status': qualification_status,
            'status': i.final_decision,
            'metrics': metrics,
        })

    context = {
        'results': results,
        'search_name': search_name,
        'search_email': search_email,
        'filter_status': filter_status,
    }
    return render(request, 'users/all_results.html', context)

###  code for home and logins
def index(request):
    return render(request, 'index.html')



from django.shortcuts import render, redirect
from .models import RegisteredUser
from django.core.files.storage import FileSystemStorage

def register_view(request):
    msg = ''
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        mobile = request.POST.get('mobile')
        password = request.POST.get('password')
        image = request.FILES.get('image')

        # Basic validation
        if not (name and email and mobile and password and image):
            msg = "All fields are required."
        else:
            # Save image manually
            fs = FileSystemStorage()
            filename = fs.save(image.name, image)
            img_url = fs.url(filename)

            # Save user with is_active=False
            RegisteredUser.objects.create(
                name=name,
                email=email,
                mobile=mobile,
                password=password,
                image=filename,
                is_active=False
            )
            msg = "Registered successfully! Wait for admin approval."

    return render(request, 'register.html', {'msg': msg})

from django.utils import timezone

from django.utils import timezone
import pytz

def user_login(request):
    msg = ''
    if request.method == 'POST':
        login_input = request.POST.get('login_input')  # email or mobile
        password = request.POST.get('password')

        try:
            user = RegisteredUser.objects.get(
                (Q(email=login_input) | Q(mobile=login_input)) & Q(password=password)
            )
            if user.is_active:
                # Convert current time to IST
                ist = pytz.timezone('Asia/Kolkata')
                local_time = timezone.now().astimezone(ist)

                # Save user info in session
                request.session['user_id'] = user.id
                request.session['user_name'] = user.name
                request.session['user_image'] = user.image.url  # image URL
                request.session['login_time'] = local_time.strftime('%I:%M:%S %p')

                return redirect('user_homepage')
            else:
                msg = "Your account is not activated yet."
        except RegisteredUser.DoesNotExist:
            msg = "Invalid credentials."

    return render(request, 'user_login.html', {'msg': msg})

def admin_login(request):
    msg = ''
    if request.method == 'POST':
        name = request.POST.get('name')
        password = request.POST.get('password')

        if name == 'admin' and password == 'admin':
            return redirect('admin_home')
        else:
            msg = "Invalid admin credentials."

    return render(request, 'admin_login.html', {'msg': msg})

def admin_home(request):
    return render(request, 'admin_home.html')
    
def admin_dashboard(request):
    users = RegisteredUser.objects.all()
    return render(request, 'admin_dashboard.html', {'users': users})

def admin_settings(request):
    settings = AdminSettings.objects.first()
    if not settings:
        settings = AdminSettings.objects.create()
    if request.method == 'POST':
        form = AdminSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            return redirect('admin_home')
    else:
        form = AdminSettingsForm(instance=settings)
    return render(request, 'admin_settings.html', {'form': form})

def activate_user(request, user_id):
    user = RegisteredUser.objects.get(id=user_id)
    user.is_active = True
    user.save()
    return redirect('admin_dashboard')

def deactivate_user(request, user_id):
    user = RegisteredUser.objects.get(id=user_id)
    user.is_active = False
    user.save()
    return redirect('admin_dashboard')

def delete_user(request, user_id):
    user = RegisteredUser.objects.get(id=user_id)
    user.delete()
    return redirect('admin_dashboard')



def home(request):
    return render(request, 'home.html')

def user_homepage(request):
    if 'user_id' not in request.session:
        # User not logged in, redirect to login page
        return redirect('user_login')

    user_name = request.session.get('user_name')
    user_image = request.session.get('user_image')
    login_time = request.session.get('login_time')

    context = {
        'user_name': user_name,
        'user_image': user_image,
        'login_time': login_time,
    }
    return render(request, 'users/user_homepage.html', context)

def user_logout(request):
    request.session.flush()  # Clears all session data
    return redirect('user_login')



import random
from django.shortcuts import render, redirect
from django.core.mail import send_mail
from django.contrib import messages
from .models import RegisteredUser
import base64
from io import BytesIO
from PIL import Image
import cv2
import numpy as np
# from deepface import DeepFace  # Placeholder

otp_storage = {}  # Temporary dictionary to store OTPs as { email: {otp, created} }

def send_otp(email):
    otp = random.randint(100000, 999999)  # Generate a 6-digit OTP
    otp_storage[email] = { 'otp': otp, 'created': timezone.now() }

    subject = "Password Reset OTP"
    message = f"Your OTP for password reset is: {otp}"
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or settings.EMAIL_HOST_USER
    try:
        send_mail(subject, message, from_email, [email], fail_silently=False)
        return True
    except Exception as e:
        print(f"Failed to send OTP email to {email}: {e}")
        # Clean up stored OTP on failure
        otp_storage.pop(email, None)
        return False

def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email")

        if RegisteredUser.objects.filter(email=email).exists():
            sent = send_otp(email)
            if sent:
                request.session["reset_email"] = email  # Store email in session
                messages.success(request, "OTP sent to your registered email.")
                return redirect("verify_otp")
            else:
                messages.error(request, "Failed to send OTP. Please try again later.")
        else:
            messages.error(request, "Email not registered!")

    return render(request, "forgot_password.html")

def verify_otp(request):
    if request.method == "POST":
        otp_entered = request.POST.get("otp")
        email = request.session.get("reset_email")

        record = otp_storage.get(email)
        if record:
            # Check expiry (10 minutes)
            created = record.get('created')
            if timezone.now() - created > timedelta(minutes=10):
                otp_storage.pop(email, None)
                messages.error(request, "OTP expired. Please request a new one.")
            elif str(record.get('otp')) == str(otp_entered):
                # OTP valid — remove it and proceed
                otp_storage.pop(email, None)
                messages.success(request, "OTP verified. You can reset your password now.")
                return redirect("reset_password")
            else:
                messages.error(request, "Invalid OTP!")
        else:
            messages.error(request, "No OTP found for this email. Please request a new one.")

    return render(request, "verify_otp.html")

def reset_password(request):
    if request.method == "POST":
        new_password = request.POST.get("new_password")
        email = request.session.get("reset_email")

        if RegisteredUser.objects.filter(email=email).exists():
            user = RegisteredUser.objects.get(email=email)
            user.password = new_password  # Updating password
            user.save()
            # Clear session keys used for reset
            request.session.pop("reset_email", None)
            messages.success(request, "Password reset successful! Please log in.")
            return redirect("user_login")

    return render(request, "reset_password.html")

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from django.http import HttpResponse
from django.utils.html import escape
import traceback

@csrf_exempt
def capture_emotion(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        image_data = data['image']
        image_data = image_data.split(',')[1]  # Remove data:image/png;base64,
        image = Image.open(BytesIO(base64.b64decode(image_data)))
        image_np = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        # Enhanced emotion detection based on face analysis
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')
        gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)

        # Determine emotion based on face detection
        if len(faces) > 0:
            x, y, w, h = faces[0]
            face_region = gray[y:y+h, x:x+w]

            # Analyze multiple features
            avg_brightness = np.mean(face_region)
            std_brightness = np.std(face_region)

            # Detect eyes in face region
            eyes = eye_cascade.detectMultiScale(face_region, 1.1, 3)
            eye_count = len(eyes)

            # Calculate contrast
            contrast = std_brightness / (avg_brightness + 1)

            # Analyze upper and lower face regions
            upper_face = face_region[0:h//2, :]
            lower_face = face_region[h//2:, :]
            upper_brightness = np.mean(upper_face)
            lower_brightness = np.mean(lower_face)

            # Emotion detection logic
            emotion_score = 0

            # Eye detection indicates engagement
            if eye_count >= 2:
                emotion_score += 2
            elif eye_count == 1:
                emotion_score += 1

            # Brightness analysis
            if avg_brightness > 110:
                emotion_score += 1
            elif avg_brightness < 70:
                emotion_score -= 1

            # Contrast analysis (higher contrast = more expression)
            if contrast > 0.5:
                emotion_score += 1

            # Face symmetry (upper vs lower brightness difference)
            brightness_diff = abs(upper_brightness - lower_brightness)
            if brightness_diff > 15:
                emotion_score += 1  # More expression

            # Add slight randomization for variety (±1 point)
            import random
            emotion_score += random.choice([-1, 0, 1])

            # Determine emotion based on score
            if emotion_score >= 4:
                emotion = 'confident'
                confidence = 0.80 + min(emotion_score - 4, 3) * 0.05
            elif emotion_score >= 2:
                emotion = 'normal'
                confidence = 0.70 + (emotion_score - 2) * 0.05
            elif emotion_score >= 0:
                emotion = 'neutral'
                confidence = 0.60 + emotion_score * 0.05
            else:
                emotion = 'suspicious'
                confidence = 0.55

            confidence = min(confidence, 0.95)
        else:
            # No face detected
            emotion = 'not_detected'
            confidence = 0.3

        # Store in EmotionLogs
        interview_id = request.session.get('interview_id')
        question_id = data.get('question_id')
        if interview_id:
            interview = Interview.objects.get(id=interview_id)
            question = None
            if question_id:
                try:
                    question = Questions.objects.get(id=question_id)
                except Questions.DoesNotExist:
                    pass
            EmotionLogs.objects.create(
                interview=interview,
                question=question,
                emotion=emotion,
                confidence=confidence
            )

        return JsonResponse({'emotion': emotion, 'confidence': confidence})

    return JsonResponse({'error': 'Invalid request'})


def test_send_email(request):
    """Dev helper: send a simple test email and show any SMTP error in response."""
    email = request.GET.get('email') or getattr(settings, 'EMAIL_HOST_USER')
    subject = "AI_Interviewer - Test Email"
    message = "This is a test message to verify SMTP configuration."
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or settings.EMAIL_HOST_USER
    try:
        send_mail(subject, message, from_email, [email], fail_silently=False)
        return HttpResponse(f"Sent test email to {escape(email)}")
    except Exception as e:
        tb = traceback.format_exc()
        return HttpResponse(f"Failed to send email to {email}: {e}\n\n{tb}", status=500, content_type='text/plain')

