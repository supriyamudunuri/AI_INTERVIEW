from django.contrib import admin
from .models import Candidate, InterviewResponse

@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'job_description')
    search_fields = ('name', 'email', 'job_description')

@admin.register(InterviewResponse)
class InterviewResponseAdmin(admin.ModelAdmin):
    list_display = ('candidate', 'question', 'answer', 'score')
    search_fields = ('candidate__name', 'question', 'answer')
    list_filter = ('score',)


from django.contrib import admin
from .models import RegisteredUser

@admin.register(RegisteredUser)
class RegisteredUserAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'mobile', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'email', 'mobile')
